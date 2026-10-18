import asyncio
import math
import os

import requests

from backend.auxEpreuve import x_y_to_row_col

addresseServeurSuivi = "proj103.r2.enst.fr"

# Le serveur de suivi de l'école est un service réel, partagé, et toujours en
# ligne. Rien ne doit le contacter depuis un test, une simulation ou une mise au
# point : par défaut on n'émet donc AUCUNE requête sortante. Il faut l'activer
# explicitement, au moment de l'épreuve.
#   PROJ103_SUIVI=1 python3 client_new.py      -> requêtes réelles
#   (défaut)                                   -> journalisées, non émises
ACTIF = os.environ.get("PROJ103_SUIVI", "0") == "1"


def activer(actif=True):
    """Autorise (ou interdit) les requêtes réelles vers le serveur de suivi."""
    global ACTIF
    ACTIF = bool(actif)

# Dérive mesurée empiriquement sur le robot : ~1,5 % de la distance parcourue
# et ~0,4 cm par rotation de 90°.
DERIVE_PAR_CM = 0.015
DERIVE_PAR_DEGRE = 0.0045
INCERTITUDE_INITIALE = 2.0      # cm, précision du placement à la main
INCERTITUDE_RECALAGE = 3.0      # cm, précision d'un recalage sur repère fixe

POSE_DEPART = (25.0, -25.0, 0.0)


class Odometrie:
    """Pose (x, y, cap) intégrée à partir des ticks d'encodeurs.

    Convention : cap 0° = +y, cap +90° = +x (angle positif = vers la droite).
    """

    def __init__(self, x=None, y=None, cap=None):
        self.reset(x, y, cap)

    # -------------------------------------------------------------------- état
    def reset(self, x=None, y=None, cap=None):
        depart_x, depart_y, depart_cap = POSE_DEPART
        self.x = depart_x if x is None else float(x)
        self.y = depart_y if y is None else float(y)
        self.cap = depart_cap if cap is None else float(cap)
        self.incertitude = INCERTITUDE_INITIALE
        self.distance_totale = 0.0

    @property
    def position(self):
        return (self.x, self.y)

    @property
    def case(self):
        return x_y_to_row_col(self.x, self.y)

    def __repr__(self):
        row, col = self.case
        return (f"<Odometrie x={self.x:.1f} y={self.y:.1f} cap={self.cap:.1f}° "
                f"case={row}{col} ±{self.incertitude:.1f}cm>")

    # ---------------------------------------------------------------- mise à jour
    def avancer(self, distance):
        """Intègre un déplacement rectiligne de `distance` cm selon le cap."""
        rad = math.radians(self.cap)
        self.x += distance * math.sin(rad)
        self.y += distance * math.cos(rad)
        self.distance_totale += abs(distance)
        self.incertitude += abs(distance) * DERIVE_PAR_CM

    def tourner(self, angle):
        """Intègre une rotation sur place de `angle` degrés (positif = droite)."""
        self.cap = (self.cap + angle + 180) % 360 - 180
        self.incertitude += abs(angle) * DERIVE_PAR_DEGRE

    def recaler(self, x, y, cap=None, incertitude=INCERTITUDE_RECALAGE):
        """Recale la pose sur une observation absolue (repère fixe du terrain).

        C'est le seul mécanisme qui fait DÉCROÎTRE l'incertitude. Sans lui, la
        dérive est monotone et le planificateur central finit par raisonner sur
        une carte fausse.
        """
        self.x = float(x)
        self.y = float(y)
        if cap is not None:
            self.cap = (float(cap) + 180) % 360 - 180
        self.incertitude = float(incertitude)


# --------------------------------------------------------------------- singleton
# L'API historique du projet est conservée (fonctions libres manipulant un état
# global) pour ne rien casser, mais elle délègue à cette instance.
odometrie = Odometrie()


def updateAvancer(distance):
    odometrie.avancer(distance)


def updateTourner(angle):
    odometrie.tourner(angle)


def getPosition():
    return [odometrie.x, odometrie.y]


def getAngle():
    return odometrie.cap


def getIncertitude():
    return odometrie.incertitude


def getCase():
    return odometrie.case


def resetState(x=None, y=None, cap=None):
    odometrie.reset(x, y, cap)


def recaler(x, y, cap=None):
    odometrie.recaler(x, y, cap)


# ------------------------------------------------------------ serveur de suivi
def _poster(chemin, params, timeout=2):
    """POST tolérant aux pannes : le robot ne doit jamais mourir d'un réseau HS."""
    if not ACTIF:
        print(f"[suivi] hors ligne : {chemin} {params} (PROJ103_SUIVI=1 pour émettre)")
        return True
    url = f"http://{addresseServeurSuivi}{chemin}"
    try:
        reponse = requests.post(url, params=params, timeout=timeout)
        if reponse.status_code != 200:
            print(f"[suivi] {chemin} -> HTTP {reponse.status_code}: {reponse.text[:120]}")
            return False
        return True
    except requests.RequestException as e:
        print(f"[suivi] {chemin} injoignable : {e}")
        return False


def sendPosition():
    """Déclare la position courante. x et y ne sont plus inversés."""
    return _poster("/api/pos", {"x": round(odometrie.x), "y": round(odometrie.y)})


def sendMarkerPosition(id, row, col):
    print(f"[suivi] drapeau {id} déclaré en {row}{col}")
    return _poster("/api/marker", {"id": id, "row": row, "col": col})


def startRace():
    return _poster("/api/start", {})


def stopRace():
    return _poster("/api/stop", {})


async def startSuivi(periode=1.0):
    """Tâche de fond : déclare la position toutes les `periode` secondes."""
    while True:
        await asyncio.sleep(periode)
        sendPosition()
