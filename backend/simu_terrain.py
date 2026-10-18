import math

from backend.vision import Detection, PORTEE_UTILE_CM, CAMERA_MATRIX

LARGEUR_IMAGE = 800
HAUTEUR_IMAGE = 750


def demi_ouverture_deg(largeur=LARGEUR_IMAGE):
    """Demi-angle du champ de vision horizontal, d'après la calibration."""
    f_x = CAMERA_MATRIX[0][0]
    return math.degrees(math.atan2(largeur / 2.0, f_x))


class Terrain:
    """Grille portant des drapeaux et des repères fixes.

    `drapeaux` : {id: (x_cm, y_cm)}
    `reperes`  : {id: (x_cm, y_cm)}
    """

    def __init__(self, drapeaux=None, reperes=None, portee=PORTEE_UTILE_CM,
                 demi_ouverture=None, obstacles=()):
        self.drapeaux = dict(drapeaux or {})
        self.reperes = dict(reperes or {})
        self.portee = portee
        self.demi_ouverture = (demi_ouverture if demi_ouverture is not None
                               else demi_ouverture_deg())
        self.obstacles = set(obstacles)     # cases infranchissables

    # ------------------------------------------------------------------ vision
    def visibles_depuis(self, x, y, cap):
        """Détections qu'un robot en (x, y) orienté `cap` verrait.

        Un marqueur est vu s'il est dans la portée utile ET dans le cône de
        vision. Les repères fixes, plus gros, restent lisibles deux fois plus
        loin que les drapeaux.
        """
        vues = []
        for marqueurs, est_repere in ((self.drapeaux, False), (self.reperes, True)):
            for identifiant, (mx, my) in marqueurs.items():
                dx, dy = mx - x, my - y
                distance = math.hypot(dx, dy)
                portee = self.portee * (2.0 if est_repere else 1.0)
                if distance > portee or distance < 1e-6:
                    continue
                # angle du marqueur par rapport au cap du robot
                azimut = math.degrees(math.atan2(dx, dy))
                ecart = (azimut - cap + 180) % 360 - 180
                if abs(ecart) > self.demi_ouverture:
                    continue
                # convention trigonométrique : à droite => angle négatif
                angle_vu = -ecart
                px = math.tan(math.radians(ecart)) * CAMERA_MATRIX[0][0]
                vues.append(Detection(identifiant, x_px=px, y_px=0.0,
                                      distance_cm=distance, angle_deg=angle_vu))
        return vues

    # ------------------------------------------------------------- navigation
    def case_bloquee(self, row, column):
        return (str(row).upper(), int(column)) in self.obstacles


class CameraSimulee:
    """Caméra branchée sur un Terrain et sur l'odométrie d'un robot.

    S'utilise exactement comme `backend.vision.Camera`.
    """

    def __init__(self, terrain, odometrie, bruit_distance=0.0, graine=7):
        import random
        self.terrain = terrain
        self.odometrie = odometrie
        self.bruit_distance = bruit_distance
        self._alea = random.Random(graine)
        self.appels = 0

    def detections(self, rafales=1):
        self.appels += 1
        vues = self.terrain.visibles_depuis(
            self.odometrie.x, self.odometrie.y, self.odometrie.cap)
        if self.bruit_distance:
            for d in vues:
                d.distance_cm *= 1 + self._alea.gauss(0, self.bruit_distance)
        return vues

    def drapeaux(self, rafales=5, portee=PORTEE_UTILE_CM):
        from backend.vision import interessant
        return [d for d in self.detections(rafales) if interessant(d, portee)]

    def reperes(self, rafales=5):
        from backend.vision import recalage_possible
        return [d for d in self.detections(rafales) if recalage_possible(d)]

    def liberer(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass
