import math
import random


class ControleurSimule:
    """Jumeau numérique de la carte de contrôle moteurs.

    Modèle : chaque moteur tourne exactement à la vitesse commandée (en ticks
    par 10 ms, comme la vraie carte), sans inertie. C'est volontairement
    optimiste : on ne cherche pas à simuler la physique fine, mais à valider la
    logique d'asservissement, de comptage de ticks et de sécurité.
    """

    I2C_ADDR = 0x57

    def __init__(self, dt=0.01, diametre_roue=None, entraxe=None,
                 ticks_par_tour=None, gain_distance=None,
                 bruit=0.0, desequilibre=1.0, graine=1234):
        self.dt = dt                      # pas de temps virtuel par lecture d'encodeurs
        self.temps = 0.0                  # horloge virtuelle (s)
        self.vitesse = (0, 0)             # ticks / 10 ms
        self.ticks_cumules = [0.0, 0.0]   # ticks non encore lus (gauche, droite)
        self.total = [0, 0]               # ticks lus depuis le début
        self.timeout = 2.0
        self.dernier_ordre = 0.0
        self.standby = False

        # Blocage physique : simule un robot coincé (autre robot, mur, tapis).
        # Les moteurs forcent mais les roues ne tournent plus.
        self.bloque = False

        # Imperfections : `bruit` est l'écart-type relatif par roue (glissement,
        # irrégularités du sol), `desequilibre` le rapport de puissance du
        # moteur droit sur le gauche. Un robot parfait ne prouve rien.
        self.bruit = bruit
        self.desequilibre = desequilibre
        self._alea = random.Random(graine)

        # Géométrie : on reprend les constantes CALIBRÉES du robot réel, afin
        # que la « vérité terrain » du simulateur soit directement comparable à
        # l'odométrie. Un écart dans un test signale alors un vrai bug de la
        # boucle d'asservissement, pas un simple décalage de calibration.
        from moteurs import controleMoteurs as cm
        self.diametre_roue = cm.DIAMETRE_ROUE if diametre_roue is None else diametre_roue
        self.entraxe = cm.ENTRAXE_EFFECTIF if entraxe is None else entraxe
        self.ticks_par_tour = cm.TICKS_PAR_TOUR if ticks_par_tour is None else ticks_par_tour
        self.gain_distance = cm.GAIN_DISTANCE if gain_distance is None else gain_distance
        self.pose_reelle = [0.0, 0.0, 0.0]  # x, y, cap (degrés)

    # ---------------------------------------------------------------- interface
    def who_am_i(self):
        return self.I2C_ADDR

    def check_who_am_i(self):
        return None

    def check_firmware_version(self):
        return None

    def get_firmware_version(self):
        return (1, 0, 0)

    def set_motor_shutdown_timeout(self, duration):
        if duration < 0.1 or duration > 10.0:
            raise ValueError(duration)
        self.timeout = duration

    def get_motor_shutdown_timeout(self):
        return self.timeout

    def set_motor_speed(self, left, right):
        for v, nom in ((left, "left"), (right, "right")):
            if v < -32767 or v > 32767:
                raise ValueError(f"{nom} motor speed must be between -32767 and 32767")
        self.vitesse = (left, right)
        self.dernier_ordre = self.temps
        self.standby = False

    def get_motor_speed(self):
        return None if self.standby else self.vitesse

    def standby_mode(self):
        self.standby = True
        self.vitesse = (0, 0)

    def get_status(self):
        bouge = self.vitesse != (0, 0) and not self.bloque
        return {"moving": bouge, "controlled": not self.standby}

    def get_encoder_ticks(self):
        """Avance l'horloge virtuelle de `dt` et renvoie les ticks accumulés."""
        self._avancer_temps(self.dt)
        g = int(self.ticks_cumules[0])
        d = int(self.ticks_cumules[1])
        self.ticks_cumules[0] -= g
        self.ticks_cumules[1] -= d
        self.total[0] += g
        self.total[1] += d
        return (g, d)

    # ----------------------------------------------------------------- physique
    def _avancer_temps(self, duree):
        self.temps += duree

        # Sécurité firmware : coupure si plus d'ordre reçu depuis `timeout`.
        if self.temps - self.dernier_ordre > self.timeout:
            self.vitesse = (0, 0)

        if self.bloque:
            return

        # vitesse en ticks/10ms -> ticks sur `duree` secondes
        dg = self.vitesse[0] * duree / 0.01
        dd = self.vitesse[1] * duree / 0.01 * self.desequilibre
        if self.bruit:
            dg *= 1 + self._alea.gauss(0, self.bruit)
            dd *= 1 + self._alea.gauss(0, self.bruit)
        self.ticks_cumules[0] += dg
        self.ticks_cumules[1] += dd
        self._integrer_pose(dg, dd)

    def _integrer_pose(self, dg, dd):
        """Odométrie différentielle de référence (la « vérité terrain »)."""
        circonference = math.pi * self.diametre_roue
        dist_g = dg * circonference / self.ticks_par_tour * self.gain_distance
        dist_d = dd * circonference / self.ticks_par_tour * self.gain_distance
        avance = (dist_g + dist_d) / 2.0
        rotation = math.degrees((dist_g - dist_d) / self.entraxe)

        cap = math.radians(self.pose_reelle[2])
        self.pose_reelle[0] += avance * math.sin(cap)
        self.pose_reelle[1] += avance * math.cos(cap)
        self.pose_reelle[2] = (self.pose_reelle[2] + rotation + 180) % 360 - 180

    # -------------------------------------------------------------------- tests
    def bloquer(self, valeur=True):
        """Coince le robot : les moteurs tournent, les roues non."""
        self.bloque = valeur


def robot_simule(bruit=0.0, desequilibre=1.0, **kwargs):
    """Fabrique un RobotController adossé à un simulateur cohérent.

    Renvoie (robot, controleur, odometrie). L'horloge du robot est l'horloge
    virtuelle du simulateur : les tests sont déterministes et instantanés.
    """
    from moteurs.controleMoteurs import RobotController
    from backend.suiviDeplacement import Odometrie

    controleur = ControleurSimule(bruit=bruit, desequilibre=desequilibre)
    odometrie = Odometrie(**kwargs)
    robot = RobotController(controleur=controleur, odometrie=odometrie,
                            horloge=lambda: controleur.temps)
    robot.periode = 0          # aucune attente réelle
    return robot, controleur, odometrie
