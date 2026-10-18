import asyncio
import math

from backend import suiviDeplacement
from backend.auxEpreuve import (RANGS, NB_COLONNES, case_vers_nom,
                                row_col_to_x_y, x_y_to_row_col)
from backend.deplacement import aller_a_case, tourner
from backend.simu_terrain import demi_ouverture_deg
from backend.vision import (recalage_possible, pose_depuis_repere,
                            position_marqueur)
from moteurs.controleMoteurs import ErreurDeplacement, RobotBloque

# Recouvrement de 20 % entre deux orientations successives, pour ne pas laisser
# de trou angulaire entre deux observations.
PAS_SCAN_DEFAUT = max(5.0, demi_ouverture_deg() * 2 * 0.8)


def itineraire_serpentin(colonnes=None, rangs=None):
    """Parcours en serpentin de la grille : on monte une colonne, on redescend
    la suivante. C'est le trajet le plus court qui visite toutes les cases.

    >>> itineraire_serpentin(colonnes=(1, 2), rangs=("F", "E"))
    [('F', 1), ('E', 1), ('E', 2), ('F', 2)]
    """
    colonnes = tuple(colonnes) if colonnes else tuple(range(1, NB_COLONNES + 1))
    rangs = tuple(rangs) if rangs else RANGS          # F -> A, du plus proche au plus loin

    trajet = []
    for indice, colonne in enumerate(colonnes):
        ordre = rangs if indice % 2 == 0 else tuple(reversed(rangs))
        trajet.extend((rang, colonne) for rang in ordre)
    return trajet


class Balayage:
    """Explore la grille, repère les drapeaux et les déclare au serveur de suivi.

    Le robot ne dispose d'aucun capteur d'obstacle : la seule détection possible
    est le blocage des roues. Quand il survient, la case visée est mémorisée
    comme infranchissable et le balayage continue ailleurs, au lieu de pousser
    indéfiniment comme le faisait la version d'origine.
    """

    def __init__(self, robot, camera, envoyer=None, pas_scan=PAS_SCAN_DEFAUT,
                 arc_scan=360.0, drapeaux_connus=None, journal=print,
                 rejoindre_drapeau=True):
        self.robot = robot
        self.camera = camera
        self.envoyer = envoyer or suiviDeplacement.sendMarkerPosition
        self.pas_scan = pas_scan
        # Arc balayé à chaque case. 360° garantit l'absence d'angle mort, au
        # prix d'environ 23 orientations par case (le champ de vision ne fait
        # que 19,7°). Le réduire accélère le balayage mais laisse des trous ;
        # comme le serpentin aborde chaque case sous plusieurs angles, 180°
        # reste un compromis défendable quand le temps est compté.
        self.arc_scan = arc_scan
        self.journal = journal
        # Le geste de capture se fait sur la case du drapeau : on s'y rend
        # d'abord. La version d'origine déclarait la case où le robot se
        # trouvait au moment où il apercevait le drapeau, à 60 cm de là.
        self.rejoindre_drapeau = rejoindre_drapeau

        self.drapeaux_vus = dict(drapeaux_connus or {})   # id -> nom de case
        self.cases_bloquees = set()
        self.cases_visitees = []

    # ------------------------------------------------------------- observation
    async def observer(self):
        """Une observation : recalage d'odométrie puis relevé des drapeaux."""
        detections = self.camera.detections(rafales=5)
        nouveaux = []

        for detection in detections:
            if recalage_possible(detection):
                self._recaler(detection)

        for detection in detections:
            if not detection.est_drapeau:
                continue
            if detection.id in self.drapeaux_vus:
                continue
            nouveaux.append(detection)
        return nouveaux

    def _recaler(self, detection):
        """Annule la dérive d'odométrie à partir d'un repère fixe du terrain."""
        try:
            x, y = pose_depuis_repere(detection, self.robot.odometrie.cap)
        except ValueError:
            return
        avant = (self.robot.odometrie.x, self.robot.odometrie.y)
        self.robot.odometrie.recaler(x, y)
        ecart = math.dist(avant, (x, y))
        self.journal(f"[autonome] recalage sur repère {detection.id} : "
                     f"correction de {ecart:.1f} cm")

    # ----------------------------------------------------------------- capture
    async def capturer(self, detection):
        """Rejoint la case du drapeau, exécute le geste de capture, déclare."""
        odo = self.robot.odometrie
        if self.rejoindre_drapeau:
            cible = x_y_to_row_col(*position_marqueur(detection, odo.x, odo.y, odo.cap))
            if cible != odo.case:
                self.journal(f"[autonome] drapeau {detection.id} estimé en "
                             f"{case_vers_nom(*cible)}, on s'y rend")
                if not await self.rejoindre(*cible):
                    self.journal(f"[autonome] {case_vers_nom(*cible)} inaccessible, "
                                 f"capture depuis la position courante")
        await tourner(self.robot, 360, sequential=True)
        row, column = odo.case
        nom = case_vers_nom(row, column)
        self.drapeaux_vus[detection.id] = nom
        self.journal(f"[autonome] drapeau {detection.id} capturé en {nom} "
                     f"(vu à {detection.distance_cm:.0f} cm)")
        self.envoyer(detection.id, row, column)
        return nom

    # ----------------------------------------------------------------- balayage
    async def scanner_case(self):
        """Tour d'horizon complet de la case courante.

        Le robot revient à son cap de départ, quoi qu'il arrive — c'est ce que
        la version d'origine ne garantissait pas.
        """
        trouves = []
        tourne = 0.0
        nb_pas = max(1, int(round(self.arc_scan / self.pas_scan)))
        pas = self.arc_scan / nb_pas

        try:
            for _ in range(nb_pas):
                for detection in await self.observer():
                    trouves.append(detection)
                    await self.capturer(detection)
                await tourner(self.robot, pas)
                tourne += pas
        finally:
            # On revient toujours au cap de départ, même interrompu : sinon le
            # cap réel et le cap supposé divergent pour tout le reste.
            if abs(tourne) > 1.0:
                retour = (-tourne) % 360.0 if self.arc_scan >= 360 else -tourne
                if abs(retour) > 1.0:
                    await tourner(self.robot, retour)
        return trouves

    async def rejoindre(self, row, column):
        """Va à une case. Renvoie False si elle s'avère inaccessible."""
        nom = case_vers_nom(row, column)
        if nom in self.cases_bloquees:
            return False
        try:
            await aller_a_case(self.robot, row, column)
            return True
        except RobotBloque as e:
            self.cases_bloquees.add(nom)
            self.journal(f"[autonome] {nom} infranchissable ({e}) -> contournement")
            return False
        except ErreurDeplacement as e:
            self.journal(f"[autonome] échec de déplacement vers {nom} : {e}")
            return False

    async def executer(self, itineraire=None):
        """Balaie la grille entière (ou l'itinéraire fourni)."""
        itineraire = itineraire or itineraire_serpentin()
        suiviDeplacement.startRace()
        self.robot.start_sending_coordinates()
        try:
            for row, column in itineraire:
                if not await self.rejoindre(row, column):
                    continue
                self.cases_visitees.append(case_vers_nom(row, column))
                await self.scanner_case()
            return self.drapeaux_vus
        finally:
            self.robot.stop_sending_coordinates()
            suiviDeplacement.stopRace()


async def epreuve3(robot, camera=None, **kwargs):
    """Point d'entrée historique, désormais une coroutine (cf. docstring module)."""
    if camera is None:
        from backend.vision import Camera
        camera = Camera()
    suiviDeplacement.resetState()
    return await Balayage(robot, camera, **kwargs).executer()
