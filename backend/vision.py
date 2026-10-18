import math

import numpy as np

# Calibration de la caméra du robot (markeurs_Aruco/proprietes_camera.txt)
CAMERA_MATRIX = np.array([[2.30625386e+03, 0.00000000e+00, 3.99080524e+02],
                          [0.00000000e+00, 2.40129695e+03, 3.74458653e+02],
                          [0.00000000e+00, 0.00000000e+00, 1.00000000e+00]])
DIST_COEFFS = np.array([[-2.23801331e-01, 6.12934477e+00, 6.37606734e-03,
                         9.27595568e-03, -4.12954773e+01]])

DICTIONNAIRE = "DICT_6X6_250"

# Identifiants des repères fixes du terrain, par opposition aux drapeaux.
MARQUEURS_REPERES = frozenset({1, 2, 3, 4})
TAILLE_REPERE = 0.048      # m
TAILLE_DRAPEAU = 0.011     # m

# Portée au-delà de laquelle l'estimation de distance n'est plus fiable.
PORTEE_UTILE_CM = 60.0

# Positions connues des repères fixes, en cm dans le repère de la grille :
#   {id: (x, y)}
# À RENSEIGNER avec le plan réel du terrain. Dès qu'il est rempli,
# `pose_depuis_repere` permet d'annuler la dérive d'odométrie (cf.
# strategie/protocole.md, section « budget de dérive »).
REPERES_FIXES = {}


class Detection:
    """Un marqueur vu dans une image."""

    __slots__ = ("id", "x_px", "y_px", "distance_cm", "angle_deg", "tvec", "rvec")

    def __init__(self, id, x_px, y_px, distance_cm, angle_deg, tvec=None, rvec=None):
        self.id = int(id)
        self.x_px = float(x_px)
        self.y_px = float(y_px)
        self.distance_cm = float(distance_cm)
        self.angle_deg = float(angle_deg)
        self.tvec = tvec
        self.rvec = rvec

    @property
    def est_repere(self):
        return self.id in MARQUEURS_REPERES

    @property
    def est_drapeau(self):
        return not self.est_repere

    def ligne(self):
        """Format imposé par tests_projet.sh : 'ID x y dist angle'."""
        def entier(valeur):          # évite les « -0 » disgracieux
            arrondi = round(valeur)
            return 0 if arrondi == 0 else arrondi
        return (f"{self.id} {entier(self.x_px)} {entier(self.y_px)} "
                f"{entier(self.distance_cm)} {entier(self.angle_deg)}")

    def __repr__(self):
        nature = "repère" if self.est_repere else "drapeau"
        return (f"<Detection {nature} id={self.id} d={self.distance_cm:.1f}cm "
                f"angle={self.angle_deg:+.1f}° px=({self.x_px:.0f},{self.y_px:.0f})>")


def taille_marqueur(marker_id):
    """Côté du marqueur en mètres, selon son identifiant."""
    return TAILLE_REPERE if int(marker_id) in MARQUEURS_REPERES else TAILLE_DRAPEAU


def mesurer(marker_id, tvec, centre_px, taille_image):
    """Construit une Detection à partir d'un vecteur de translation caméra.

    `tvec` est en mètres dans le repère caméra (x droite, y bas, z avant),
    `centre_px` le centre du marqueur en pixels image, `taille_image` (largeur,
    hauteur).

    Conventions de sortie (tests_projet.sh) :
      - x_px : 0 au centre de l'image, croissant vers la droite
      - y_px : 0 au centre de l'image, croissant vers le HAUT
      - distance en cm
      - angle en degrés, sens trigonométrique : un marqueur à droite de l'axe
        optique a un angle négatif
    """
    tx, ty, tz = (float(v) for v in np.asarray(tvec).reshape(3))
    distance_cm = math.sqrt(tx * tx + ty * ty + tz * tz) * 100.0
    angle_deg = -math.degrees(math.atan2(tx, tz))

    largeur, hauteur = taille_image
    u, v = centre_px
    return Detection(marker_id,
                     x_px=u - largeur / 2.0,
                     y_px=hauteur / 2.0 - v,
                     distance_cm=distance_cm,
                     angle_deg=angle_deg,
                     tvec=(tx, ty, tz))


def interessant(detection, portee=PORTEE_UTILE_CM):
    """Le marqueur est-il un drapeau exploitable ?

    L'ancien filtre `(id > 4 or id == 0)` revenait au même, mais écartait aussi
    les repères fixes, que l'on veut désormais conserver pour le recalage.
    """
    return detection.est_drapeau and detection.distance_cm <= portee


def recalage_possible(detection):
    """La detection permet-elle de recaler l'odométrie sur une position connue ?"""
    return detection.est_repere and detection.id in REPERES_FIXES


def pose_depuis_repere(detection, cap_robot):
    """Position absolue (x, y) du robot déduite d'un repère fixe connu.

    On connaît la position du repère, la distance mesurée et le relèvement du
    repère dans le repère du robot. Combinés au cap du robot, cela détermine
    entièrement sa position :

        azimut_du_repère = cap_robot - angle_mesuré
        robot = repère - distance * (sin azimut, cos azimut)

    Le cap intervient, pas la normale du marqueur : avec la seule distance et le
    seul relèvement, le robot serait n'importe où sur un cercle autour du
    repère. C'est volontairement le cap qui sert de référence, car il dérive
    bien plus lentement que la position (une erreur d'angle ne s'intègre pas).
    """
    if not recalage_possible(detection):
        raise ValueError(f"repère {detection.id} de position inconnue")
    rx, ry = REPERES_FIXES[detection.id][:2]
    azimut = math.radians(cap_robot - detection.angle_deg)
    return (rx - detection.distance_cm * math.sin(azimut),
            ry - detection.distance_cm * math.cos(azimut))


def position_marqueur(detection, x_robot, y_robot, cap_robot):
    """Position absolue (x, y) d'un marqueur vu depuis une pose connue.

    Réciproque de `pose_depuis_repere` : sert à savoir vers quelle case aller
    pour capturer un drapeau qu'on vient d'apercevoir.
    """
    azimut = math.radians(cap_robot - detection.angle_deg)
    return (x_robot + detection.distance_cm * math.sin(azimut),
            y_robot + detection.distance_cm * math.cos(azimut))


# ----------------------------------------------------------------- OpenCV
def _charger_cv2():
    try:
        import cv2
        import cv2.aruco as aruco
        return cv2, aruco
    except ImportError as e:
        raise RuntimeError(
            "OpenCV (cv2) est requis pour la détection réelle. "
            "Installer avec : sudo apt install python3-opencv"
        ) from e


def _detecteur(aruco):
    """Compatibilité OpenCV 4.6 (API `_create`) et 4.7+ (API objet)."""
    dictionnaire = getattr(aruco, DICTIONNAIRE)
    if hasattr(aruco, "Dictionary_get"):
        return aruco.Dictionary_get(dictionnaire), aruco.DetectorParameters_create()
    return (aruco.getPredefinedDictionary(dictionnaire), aruco.DetectorParameters())


def _detecter(aruco, gris, dico, params):
    if hasattr(aruco, "ArucoDetector"):
        return aruco.ArucoDetector(dico, params).detectMarkers(gris)
    return aruco.detectMarkers(gris, dico, parameters=params)


def _estimer_pose(aruco, coins, taille):
    if hasattr(aruco, "estimatePoseSingleMarkers"):
        rvecs, tvecs, _ = aruco.estimatePoseSingleMarkers(
            coins, taille, CAMERA_MATRIX, DIST_COEFFS)
        return rvecs, tvecs
    # OpenCV 4.7+ : estimatePoseSingleMarkers est retiré, on passe par solvePnP
    import cv2
    demi = taille / 2.0
    objet = np.array([[-demi, demi, 0], [demi, demi, 0],
                      [demi, -demi, 0], [-demi, -demi, 0]], dtype=np.float32)
    rvecs, tvecs = [], []
    for coin in coins:
        _, rvec, tvec = cv2.solvePnP(objet, coin.reshape(4, 2),
                                     CAMERA_MATRIX, DIST_COEFFS)
        rvecs.append(rvec.reshape(1, 3))
        tvecs.append(tvec.reshape(1, 3))
    return np.array(rvecs), np.array(tvecs)


def detections_dans_image(image):
    """Toutes les détections d'une image (tableau numpy BGR)."""
    cv2, aruco = _charger_cv2()
    dico, params = _detecteur(aruco)
    gris = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    coins, ids, _ = _detecter(aruco, gris, dico, params)
    if ids is None or len(ids) == 0:
        return []

    hauteur, largeur = gris.shape[:2]
    resultats = []
    for i, identifiant in enumerate(ids.flatten()):
        rvecs, tvecs = _estimer_pose(aruco, [coins[i]], taille_marqueur(identifiant))
        centre = coins[i].reshape(4, 2).mean(axis=0)
        detection = mesurer(identifiant, tvecs[0], centre, (largeur, hauteur))
        detection.rvec = tuple(float(v) for v in np.asarray(rvecs[0]).reshape(3))
        resultats.append(detection)
    return resultats


def detections_dans_fichier(chemin):
    """Détections d'un fichier image (utilisé par `tests_projet.sh camera`)."""
    cv2, _ = _charger_cv2()
    image = cv2.imread(str(chemin))
    if image is None:
        raise FileNotFoundError(f"image illisible : {chemin}")
    return detections_dans_image(image)


class Camera:
    """Flux caméra. Les premières images d'un flux qui démarre sont ignorées."""

    IMAGES_A_JETER = 5

    def __init__(self, source=0, simulee=None):
        self.source = source
        self.simulee = simulee        # callable renvoyant une liste de Detection
        self._cap = None

    def _ouvrir(self):
        if self._cap is None and self.simulee is None:
            cv2, _ = _charger_cv2()
            backend = getattr(cv2, "CAP_V4L", 0)
            self._cap = cv2.VideoCapture(self.source, backend)
            if not self._cap.isOpened():
                raise RuntimeError(f"caméra {self.source} inaccessible")
        return self._cap

    def detections(self, rafales=1):
        """Lit `rafales` images et renvoie l'union des détections."""
        if self.simulee is not None:
            return list(self.simulee())

        cap = self._ouvrir()
        for _ in range(self.IMAGES_A_JETER):
            cap.read()

        vues = {}
        for _ in range(max(1, rafales)):
            ok, image = cap.read()
            if not ok:
                continue
            for detection in detections_dans_image(image):
                # à identifiant égal, on garde la mesure la plus proche
                ancienne = vues.get(detection.id)
                if ancienne is None or detection.distance_cm < ancienne.distance_cm:
                    vues[detection.id] = detection
        return list(vues.values())

    def drapeaux(self, rafales=5, portee=PORTEE_UTILE_CM):
        return [d for d in self.detections(rafales) if interessant(d, portee)]

    def reperes(self, rafales=5):
        return [d for d in self.detections(rafales) if recalage_possible(d)]

    def liberer(self):
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.liberer()
