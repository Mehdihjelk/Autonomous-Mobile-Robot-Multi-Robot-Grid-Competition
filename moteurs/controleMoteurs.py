#!/usr/bin/env python3

import math
import time
import threading
import asyncio

import requests

from backend import suiviDeplacement

# --------------------------------------------------------------- calibration
# Mesurée sur le robot de team1. Chaque constante est utilisée DANS LES DEUX
# SENS (commande et mesure) : c'était l'autre bug de fond de l'odométrie, les
# corrections n'étaient appliquées qu'à la commande, ce qui donnait une erreur
# systématique de 1,7 % en distance et 2,2 % en angle à chaque mouvement.
DIAMETRE_ROUE = 6.5          # cm
TICKS_PAR_TOUR = 3840
ENTRAXE = 18.5               # cm, mesuré au pied à coulisse

# Le robot avance 1,7 % de plus que ce que prédit la géométrie (glissement,
# diamètre réel des roues) : l'équipe avait trouvé le facteur 1 - 0,05/3.
GAIN_DISTANCE = 1 / (1 - 0.05 / 3)

# La géométrie prédisait 360° là où le robot tournait de 368° : l'entraxe
# effectif est donc légèrement plus court que l'entraxe mesuré.
ENTRAXE_EFFECTIF = ENTRAXE * 360 / 368


class Awaken(Exception):
    pass


class ErreurDeplacement(Exception):
    """Base des échecs de mouvement : le mouvement est interrompu, moteurs à l'arrêt."""


class RobotBloque(ErreurDeplacement):
    """Les roues ne tournent plus alors que les moteurs sont commandés.

    Obstacle physique : autre robot, mur, câble. La stratégie de groupe
    s'appuie sur cette exception pour mettre la case suivante en quarantaine.
    """


class MouvementTropLong(ErreurDeplacement):
    """Le mouvement n'a pas convergé dans le temps imparti."""


def _borner(valeur, limite):
    """Borne symétrique dans [-|limite|, +|limite|]."""
    limite = abs(limite)
    return max(-limite, min(limite, valeur))


def _ouvrir_controleur(simulation=None):
    """Renvoie un contrôleur moteurs : carte I2C réelle, sinon simulateur.

    `simulation=None` : autodétection (on tente le bus I2C, on retombe sur le
    simulateur si `smbus` est absent ou la carte muette).
    """
    if simulation is True:
        from moteurs.simu import ControleurSimule
        return ControleurSimule(), True
    if simulation is False:
        from moteurs import controller
        return controller.Controller(), False
    try:
        from moteurs import controller
        return controller.Controller(), False
    except Exception as e:                      # smbus absent, carte muette...
        from moteurs.simu import ControleurSimule
        print(f"[moteurs] carte I2C indisponible ({e}) -> simulateur")
        return ControleurSimule(), True


class RobotController:
    """Pilote le robot en distances (cm) et angles (degrés)."""

    def __init__(self, simulation=None, odometrie=None, horloge=time.monotonic,
                 controleur=None):
        if controleur is not None:
            self.controller, self.simule = controleur, True
        else:
            self.controller, self.simule = _ouvrir_controleur(simulation)
        self.controller.set_motor_shutdown_timeout(2)

        # La pose vit dans backend.suiviDeplacement : une seule source de vérité.
        self.odometrie = odometrie or suiviDeplacement.odometrie
        self.horloge = horloge

        # --- géométrie et calibration (valeurs mesurées sur le robot) ---------
        self.speed = 35            # ticks par 10 ms en régime de croisière
        self.minSpeed = 15         # plancher : en dessous, les moteurs calent
        self.entraxe = ENTRAXE
        self.entraxeEffectif = ENTRAXE_EFFECTIF
        self.diametreRoue = DIAMETRE_ROUE
        self.ticksParTour = TICKS_PAR_TOUR
        self.gainDistance = GAIN_DISTANCE
        self.correction = 1.0      # >1 accélère le moteur gauche, <1 le ralentit
        self.Kp = 0.85
        self.Kd_roues = 0.7        # recalage d'une roue sur l'autre

        # Si le moteur droit est monté en miroir sur ton robot (le robot avance
        # au lieu de tourner), passer cette valeur à -1 : la commande ET la
        # lecture d'encodeur droites sont alors inversées ensemble.
        self.inversion_droite = 1

        # --- sécurité --------------------------------------------------------
        self.periode = 0.01            # pas de la boucle d'asservissement (s)
        self.fenetre_blocage = 0.4     # s sans progression avant de crier
        self.ticks_min_progres = 8     # ticks minimum sur cette fenêtre
        self.marge_duree = 4.0         # facteur sur la durée théorique
        self.duree_min = 2.0           # s, plancher du budget de durée

        self.tolerance_distance = 0.25  # cm
        self.tolerance_angle = 0.30     # cm d'arc

        self.etat = False              # thread d'envoi de position actif ?
        self.lastDir = "Stop"
        self.moveDict = {
            "Avancer": [self.speed, self.speed],
            "Reculer": [-self.speed, -self.speed],
            "Gauche": [-self.speed, self.speed],
            "Droite": [self.speed, -self.speed],
            "Stop": [0, 0],
        }

    # ------------------------------------------------------------- conversions
    # ticks_to_* et *_to_ticks sont réciproques : c'est ce qui garantit que
    # l'odométrie mesure dans la même unité que celle dans laquelle on commande.
    def _distance_geometrique(self, ticks):
        return ticks * math.pi * self.diametreRoue / self.ticksParTour

    def ticks_to_distance(self, ticks):
        return self._distance_geometrique(ticks) * self.gainDistance

    def distance_to_ticks(self, distance):
        reelle = distance / self.gainDistance
        return int(reelle * self.ticksParTour / (math.pi * self.diametreRoue))

    def angle_to_ticks(self, angle_deg):
        arc = self.entraxeEffectif * math.radians(angle_deg) / 2
        return self.distance_to_ticks(arc)

    def ticks_to_angle(self, ticks):
        return math.degrees(self.ticks_to_distance(ticks) * 2 / self.entraxeEffectif)

    # --------------------------------------------------------- pilotage direct
    def _commander(self, gauche, droite):
        self.controller.set_motor_speed(
            int(gauche * self.correction),
            int(droite * self.inversion_droite),
        )

    def _lire_encodeurs(self):
        gauche, droite = self.controller.get_encoder_ticks()
        return gauche, droite * self.inversion_droite

    def move(self, direction):
        """Pilotage manuel (interface web) : vitesse constante jusqu'à nouvel ordre."""
        if direction not in self.moveDict:
            raise ValueError(f"direction inconnue : {direction!r}")
        gauche, droite = self.moveDict[direction]
        self._commander(gauche, droite)
        self.lastDir = direction

    def stop(self):
        self.move("Stop")

    # --------------------------------------------------- boucle d'asservissement
    async def _asservir(self, cible_gauche, cible_droite, libelle,
                        progression=None, tolerance_cm=0.25):
        """Amène chaque roue à sa cible en ticks.

        `progression(delta_ticks_gauche, delta_ticks_droite)` est appelé à chaque
        itération pour intégrer l'odométrie au fil du mouvement.

        Lève RobotBloque / MouvementTropLong, moteurs arrêtés dans tous les cas.
        """
        if cible_gauche == 0 and cible_droite == 0:
            return 0, 0

        self._lire_encodeurs()      # purge le compteur matériel
        self.stop()

        # La tolérance d'arrêt ne peut jamais dépasser le tiers du mouvement
        # demandé : sinon une petite correction serait considérée comme déjà
        # atteinte et silencieusement ignorée, et la boucle fermée du niveau
        # supérieur tournerait sans fin.
        plancher = max(abs(cible_gauche), abs(cible_droite)) // 3
        tolerance = max(1, min(self.distance_to_ticks(tolerance_cm), plancher))
        budget = max(self.duree_min, self.marge_duree * self._duree_theorique(
            max(abs(cible_gauche), abs(cible_droite))))

        debut = self.horloge()
        gcount = rcount = 0
        dernier_progres = debut
        ticks_au_dernier_progres = 0

        try:
            while True:
                dg, dd = self._lire_encodeurs()
                gcount += dg
                rcount += dd
                if progression is not None:
                    progression(dg, dd)

                g_err = cible_gauche - gcount
                d_err = cible_droite - rcount

                atteint = max(abs(g_err), abs(d_err)) < tolerance
                depasse = (abs(gcount) >= abs(cible_gauche) != 0
                           and abs(rcount) >= abs(cible_droite) != 0)
                if atteint or depasse:
                    return gcount, rcount

                maintenant = self.horloge()
                if maintenant - debut > budget:
                    raise MouvementTropLong(
                        f"{libelle} : pas convergé en {budget:.1f}s "
                        f"(gauche {gcount}/{cible_gauche}, droite {rcount}/{cible_droite})")

                # --- détection de blocage ---------------------------------
                parcouru = abs(gcount) + abs(rcount)
                if parcouru - ticks_au_dernier_progres >= self.ticks_min_progres:
                    ticks_au_dernier_progres = parcouru
                    dernier_progres = maintenant
                elif maintenant - dernier_progres > self.fenetre_blocage:
                    raise RobotBloque(
                        f"{libelle} : roues immobiles depuis {self.fenetre_blocage}s "
                        f"(gauche {gcount}/{cible_gauche}, droite {rcount}/{cible_droite})")

                # --- correcteur proportionnel + recalage inter-roues --------
                limite_g = self._vitesse_max(g_err, cible_gauche)
                limite_d = self._vitesse_max(d_err, cible_droite)
                desequilibre = gcount * _signe(cible_gauche) - rcount * _signe(cible_droite)

                sortie_g = _borner(self.Kp * g_err, limite_g)
                sortie_d = _borner(self.Kp * d_err, limite_d) \
                    + self.Kd_roues * desequilibre * _signe(cible_droite)

                self._commander(sortie_g, sortie_d)
                if self.periode:
                    await asyncio.sleep(self.periode)
                else:
                    await asyncio.sleep(0)
        finally:
            self.stop()
            if self.periode:
                await asyncio.sleep(min(0.2, self.periode * 20))

    def _vitesse_max(self, erreur, cible):
        """Vitesse plafond : décroît à l'approche de la cible, plancher minSpeed.

        C'est la décélération progressive qui évite le dérapage en fin de course,
        et la contribution la plus utile de l'équipe (documentée dans A_LIRE.txt
        et partagée avec les autres groupes).
        """
        if cible == 0:
            return self.minSpeed
        ratio = abs(erreur) / abs(cible)
        return max(self.minSpeed, self.speed * ratio)

    def _duree_theorique(self, ticks):
        """Durée idéale pour parcourir `ticks` à vitesse de croisière."""
        return abs(ticks) / max(1, self.speed) * 0.01

    # ------------------------------------------------------- mouvements publics
    async def move_distance(self, target_distance, updateDist=None):
        """Avance (ou recule si négatif) de `target_distance` cm.

        `updateDist` est un simple observateur, notifié de chaque incrément de
        distance mesuré. Il ne doit SURTOUT PAS écrire dans l'odométrie du
        robot : celle-ci est déjà mise à jour ici, et un second écrivain
        doublerait chaque mouvement.
        """
        print(f"[robot] avance de {target_distance} cm")
        cible = self.distance_to_ticks(target_distance)

        maj = self._integrateur_distance(updateDist)
        await self._asservir(cible, cible, f"avance {target_distance}cm",
                             progression=maj,
                             tolerance_cm=self.tolerance_distance)

    async def tourne_angle(self, target_angle, updateAng=None):
        """Tourne sur place de `target_angle` degrés (positif = vers la droite).

        Comme pour `move_distance`, `updateAng` observe sans écrire dans
        l'odométrie (cf. docstring de `move_distance`).
        """
        print(f"[robot] tourne de {target_angle}°")
        cible = self.angle_to_ticks(target_angle)

        maj = self._integrateur_angle(updateAng)
        await self._asservir(cible, -cible, f"rotation {target_angle}°",
                             progression=maj,
                             tolerance_cm=self.tolerance_angle)

    # ------------------------------------------------- intégration d'odométrie
    def _integrateur_distance(self, callback):
        """Convertit les ticks lus en avance (cm) et la pousse dans l'odométrie."""
        def maj(dg, dd):
            avance = self.ticks_to_distance((dg + dd) / 2)
            if avance:
                self.odometrie.avancer(avance)
                if callback is not None and not self._ecrit_dans_odometrie(callback):
                    callback(avance)
        return maj

    def _integrateur_angle(self, callback):
        """Convertit les ticks lus en rotation (degrés) et la pousse dans l'odométrie."""
        def maj(dg, dd):
            rotation = self.ticks_to_angle((dg - dd) / 2)
            if rotation:
                self.odometrie.tourner(rotation)
                if callback is not None and not self._ecrit_dans_odometrie(callback):
                    callback(rotation)
        return maj

    def _ecrit_dans_odometrie(self, callback):
        """Garde-fou : neutralise un callback qui écrirait dans notre odométrie.

        `suiviDeplacement.updateAvancer` / `updateTourner` écrivent dans le
        singleton d'odométrie. Si c'est aussi la nôtre — ce qui est le cas par
        défaut — les appeler ici compterait chaque mouvement deux fois. Plutôt
        que de laisser le piège ouvert, on l'écarte explicitement.
        """
        if callback in (suiviDeplacement.updateAvancer, suiviDeplacement.updateTourner):
            return self.odometrie is suiviDeplacement.odometrie
        return False

    # ------------------------------------------------------ report de position
    @property
    def x(self):
        return self.odometrie.x

    @property
    def y(self):
        return self.odometrie.y

    @property
    def angle(self):
        return self.odometrie.cap

    def send_coordinates(self):
        """Déclare la position au serveur de suivi (x et y ne sont plus inversés)."""
        ok = suiviDeplacement.sendPosition()
        if ok:
            row, col = self.odometrie.case
            print(f"[robot] position x={self.x:.0f} y={self.y:.0f} ({row}{col})")
        return ok

    def continuous_send_coordinates(self):
        while self.etat:
            self.send_coordinates()
            time.sleep(1)

    def start_sending_coordinates(self):
        if self.etat:
            return
        self.etat = True
        thread = threading.Thread(target=self.continuous_send_coordinates, daemon=True)
        thread.start()

    def stop_sending_coordinates(self):
        self.etat = False
        self.send_coordinates()


def _signe(valeur):
    return 1 if valeur >= 0 else -1
