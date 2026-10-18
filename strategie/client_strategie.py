import asyncio
import math

import requests

from backend import suiviDeplacement
from backend.auxEpreuve import case_vers_nom, nom_vers_case, row_col_to_x_y
from backend.deplacement import aller_a_case, tourner
from backend.vision import position_marqueur, recalage_possible, pose_depuis_repere
from moteurs.controleMoteurs import ErreurDeplacement, RobotBloque

PERIODE_BATTEMENT = 1.0
ATTENTE_APRES_REFUS = 0.5


class ClientStrategie:
    """Exécute le protocole de baux pour un robot."""

    def __init__(self, robot, camera, serveur="http://127.0.0.1:8080",
                 robot_id="team1", journal=print, timeout=2.0):
        self.robot = robot
        self.camera = camera
        self.serveur = serveur.rstrip("/")
        self.robot_id = robot_id
        self.journal = journal
        self.timeout = timeout

        self.baux = set()
        self.drapeaux_vus = {}
        self.inscrit = False
        self.arret_demande = False

    # ------------------------------------------------------------- transport
    def _poster(self, route, charge):
        """POST JSON. Renvoie None si le serveur est injoignable.

        Un `None` n'est jamais interprété comme une permission : le robot
        s'immobilise. C'est le comportement sûr par défaut.
        """
        try:
            reponse = requests.post(f"{self.serveur}{route}",
                                    json={"id": self.robot_id, **charge},
                                    timeout=self.timeout)
            return reponse.json()
        except (requests.RequestException, ValueError):
            return None

    def joignable(self):
        try:
            requests.get(f"{self.serveur}/api/carte", timeout=self.timeout)
            return True
        except requests.RequestException:
            return False

    # ------------------------------------------------------------ protocole
    @property
    def case(self):
        return case_vers_nom(*self.robot.odometrie.case)

    def inscrire(self):
        reponse = self._poster("/api/inscription", {"case": self.case})
        if reponse is None:
            self.journal("[strategie] serveur central injoignable")
            return False
        if not reponse.get("accord"):
            self.journal(f"[strategie] inscription refusée : {reponse.get('motif')}")
            return False
        self.inscrit = True
        self.baux = {reponse["case"]}
        self.journal(f"[strategie] inscrit sous « {self.robot_id} » en {reponse['case']}")
        return True

    def battement(self):
        return self._poster("/api/battement", {
            "case": self.case,
            "incertitude": self.robot.odometrie.incertitude,
        })

    # ------------------------------------------------------------- recalage
    async def se_recaler(self):
        """Cherche un repère fixe pour annuler la dérive d'odométrie.

        Tant que l'incertitude dépasse une demi-case, le serveur refuse tout
        bail : le robot ne peut plus garantir que son emprise tient dans les
        cases qu'il loue.
        """
        self.journal(f"[strategie] recalage requis "
                     f"(±{self.robot.odometrie.incertitude:.0f} cm)")
        pas = 30.0
        for _ in range(int(360 / pas)):
            for detection in self.camera.detections(rafales=3):
                if not recalage_possible(detection):
                    continue
                x, y = pose_depuis_repere(detection, self.robot.odometrie.cap)
                self.robot.odometrie.recaler(x, y)
                self.journal(f"[strategie] recalé sur le repère {detection.id} "
                             f"-> ({x:.0f}, {y:.0f})")
                return True
            await tourner(self.robot, pas)
        self.journal("[strategie] aucun repère fixe en vue, recalage impossible")
        return False

    # ------------------------------------------------------------- drapeaux
    async def relever_drapeaux(self):
        """Signale les drapeaux vus, et les capture s'ils sont sur notre case."""
        for detection in self.camera.detections(rafales=5):
            if not detection.est_drapeau or detection.id in self.drapeaux_vus:
                continue
            odo = self.robot.odometrie
            x, y = position_marqueur(detection, odo.x, odo.y, odo.cap)
            from backend.auxEpreuve import x_y_to_row_col
            nom = case_vers_nom(*x_y_to_row_col(x, y))

            self.drapeaux_vus[detection.id] = nom
            self._poster("/api/drapeau", {"drapeau": detection.id, "case": nom})
            self.journal(f"[strategie] drapeau {detection.id} signalé en {nom}")

            # Le geste de capture ne vaut que sur place : on ne le fait que si
            # le drapeau est dans notre propre case, qu'on détient déjà.
            if nom == self.case:
                await tourner(self.robot, 360)
                row, column = nom_vers_case(nom)
                suiviDeplacement.sendMarkerPosition(detection.id, row, column)

    # ------------------------------------------------------------- un cycle
    async def cycle(self):
        """Un tour de boucle. Renvoie True si le robot a progressé."""
        etat = self.battement()
        if etat is None or not etat.get("connu"):
            self.robot.stop()
            return False

        self.baux = set(etat.get("baux", []))
        if etat.get("doit_se_recaler"):
            await self.se_recaler()
            return True

        await self.relever_drapeaux()

        cible = (self._poster("/api/cible", {}) or {}).get("case")
        if not cible:
            return False

        accord = self._poster("/api/reservation", {"case": cible})
        if accord is None:
            self.robot.stop()
            return False
        if not accord.get("accord"):
            self.journal(f"[strategie] {cible} refusée : {accord.get('motif')}")
            await asyncio.sleep(ATTENTE_APRES_REFUS)
            return False

        source = self.case
        row, column = nom_vers_case(cible)
        try:
            await aller_a_case(self.robot, row, column)
        except RobotBloque as e:
            # Le monde physique contredit la carte : on le fait savoir.
            self._poster("/api/blocage", {"case": cible, "detail": str(e)})
            self.journal(f"[strategie] bloqué vers {cible}, mis en quarantaine")
            return True
        except ErreurDeplacement as e:
            self._poster("/api/blocage", {"case": cible, "detail": str(e)})
            self.journal(f"[strategie] échec vers {cible} : {e}")
            return True

        self._poster("/api/liberation", {"case": source, "arrive_en": cible})
        self.journal(f"[strategie] {source} -> {cible}")
        return True

    # ---------------------------------------------------------- boucle longue
    async def boucle(self, cycles=None):
        """Boucle principale. `cycles=None` pour tourner indéfiniment."""
        if not self.inscrit and not self.inscrire():
            return False

        self.robot.start_sending_coordinates()
        try:
            tour = 0
            while not self.arret_demande and (cycles is None or tour < cycles):
                if not await self.cycle():
                    await asyncio.sleep(PERIODE_BATTEMENT)
                tour += 1
            return True
        finally:
            self.robot.stop()
            self.robot.stop_sending_coordinates()
