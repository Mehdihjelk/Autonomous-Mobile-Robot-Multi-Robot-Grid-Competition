#!/usr/bin/env python3

import argparse
import json
import threading
import time
from collections import deque
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

from backend.auxEpreuve import (case_vers_nom, cases_voisines, nom_vers_case,
                                toutes_les_cases)

# --------------------------------------------------------------- états de case
LIBRE = "LIBRE"
RESERVEE = "RESERVEE"       # bail accordé, robot en transit vers elle
OCCUPEE = "OCCUPEE"         # bail accordé, robot dedans
QUARANTAINE = "QUARANTAINE"  # présumée encombrée, interdite jusqu'à lever

TTL_BAIL = 10.0             # s sans battement avant mise en quarantaine
SEUIL_INCERTITUDE = 25.0    # cm : demi-case, au-delà le robot doit se recaler
PRIORITE_MAX = 1_000_000


class ViolationInvariant(AssertionError):
    """L'invariant de sûreté est rompu : c'est un bug du serveur, pas du robot."""


class Robot:
    """Vue serveur d'un robot participant."""

    def __init__(self, identifiant, case, maintenant):
        self.id = identifiant
        self.baux = {case}            # cases dont il détient le bail
        self.case = case              # case où il se déclare
        self.incertitude = 0.0
        self.priorite = 0             # augmente à chaque refus (anti-famine)
        self.dernier_battement = maintenant
        self.vivant = True
        self.baux_perdus = []         # baux mis en quarantaine après sa panne
        self.cible = None             # case que le serveur lui demande d'atteindre
        self.doit_se_recaler = False
        self.drapeaux = {}

    def etat(self):
        return {
            "id": self.id,
            "case": self.case,
            "baux": sorted(self.baux),
            "incertitude": round(self.incertitude, 1),
            "priorite": self.priorite,
            "vivant": self.vivant,
            "cible": self.cible,
            "doit_se_recaler": self.doit_se_recaler,
        }


class Arbitre:
    """Cœur de la stratégie. Logique pure, sans HTTP : directement testable."""

    def __init__(self, horloge=time.monotonic, ttl=TTL_BAIL,
                 seuil_incertitude=SEUIL_INCERTITUDE):
        self.horloge = horloge
        self.ttl = ttl
        self.seuil_incertitude = seuil_incertitude
        self.verrou = threading.RLock()

        self.cases = {case_vers_nom(r, c): {"etat": LIBRE, "robot": None,
                                            "raison": None, "depuis": 0.0}
                      for r, c in toutes_les_cases()}
        self.robots = {}
        self.drapeaux = {}            # id drapeau -> case déclarée
        self.explorees = set()
        self.journal = deque(maxlen=500)

    # ------------------------------------------------------------------ outils
    def _noter(self, message):
        self.journal.append((round(self.horloge(), 2), message))

    def _case(self, nom):
        if nom not in self.cases:
            raise KeyError(f"case hors grille : {nom}")
        return self.cases[nom]

    def _attribuer(self, nom, etat, robot_id, raison=None):
        case = self._case(nom)
        case.update({"etat": etat, "robot": robot_id, "raison": raison,
                     "depuis": self.horloge()})

    # ------------------------------------------------------------- inscription
    def inscrire(self, robot_id, case_depart):
        """Enregistre un robot et lui accorde le bail de sa case de départ."""
        with self.verrou:
            nom = case_vers_nom(*nom_vers_case(case_depart))
            case = self._case(nom)
            if case["etat"] == QUARANTAINE:
                return {"accord": False, "motif": f"{nom} en quarantaine"}
            if case["etat"] in (RESERVEE, OCCUPEE) and case["robot"] != robot_id:
                return {"accord": False,
                        "motif": f"{nom} déjà louée à {case['robot']}"}

            maintenant = self.horloge()
            if robot_id in self.robots:
                # réinscription après redémarrage : on reprend ses baux
                robot = self.robots[robot_id]
                robot.vivant = True
                robot.dernier_battement = maintenant
            else:
                robot = Robot(robot_id, nom, maintenant)
                self.robots[robot_id] = robot

            robot.case = nom
            robot.baux = {nom}
            self._attribuer(nom, OCCUPEE, robot_id)
            self.explorees.add(nom)
            self._noter(f"{robot_id} inscrit en {nom}")
            return {"accord": True, "case": nom, "ttl": self.ttl}

    # --------------------------------------------------------------- battement
    def battement(self, robot_id, case=None, incertitude=0.0):
        """Battement de cœur : prolonge les baux et renvoie les consignes.

        C'est la seule chose qui maintient un bail en vie. Son absence vaut
        panne, et une panne vaut quarantaine — pas libération.
        """
        with self.verrou:
            robot = self.robots.get(robot_id)
            if robot is None:
                return {"connu": False, "motif": "robot non inscrit"}

            robot.dernier_battement = self.horloge()
            robot.vivant = True
            robot.incertitude = float(incertitude)
            if case:
                nom = case_vers_nom(*nom_vers_case(case))
                if nom in robot.baux:
                    robot.case = nom

            # Dérive : au-delà d'une demi-case, la position déclarée ne permet
            # plus de garantir que l'emprise du robot tient dans ses baux.
            robot.doit_se_recaler = robot.incertitude > self.seuil_incertitude

            self._expirer_sans_verrou()
            return {
                "connu": True,
                "baux": sorted(robot.baux),
                "cible": robot.cible,
                "doit_se_recaler": robot.doit_se_recaler,
                "quarantaines": self.quarantaines(),
                "drapeaux": dict(self.drapeaux),
            }

    # -------------------------------------------------------------- expiration
    def expirer(self):
        with self.verrou:
            return self._expirer_sans_verrou()

    def _expirer_sans_verrou(self):
        """Met en quarantaine les baux des robots qui ne battent plus.

        Point crucial : on ne libère pas. Un robot muet est probablement en
        panne ET toujours posé sur la grille. Le libérer enverrait un autre
        robot lui rentrer dedans — c'était exactement le défaut de la
        « tolérance aux pannes » d'origine.
        """
        maintenant = self.horloge()
        perdus = []
        for robot in self.robots.values():
            if not robot.vivant:
                continue
            if maintenant - robot.dernier_battement <= self.ttl:
                continue
            robot.vivant = False
            perdus.append(robot.id)
            perdues = sorted(robot.baux)
            for nom in perdues:
                self._attribuer(nom, QUARANTAINE, None,
                                raison=f"{robot.id} muet depuis {self.ttl}s")
            # Le robot ne détient plus rien : la case est en quarantaine, donc
            # retenue par PERSONNE. Laisser le bail dans `baux` en ferait un
            # bail fantôme, qui ressurgirait à la levée de la quarantaine et
            # permettrait à deux robots de revendiquer la même case.
            robot.baux_perdus = perdues
            robot.baux = set()
            self._noter(f"{robot.id} présumé en panne -> {perdues} "
                        f"en quarantaine (NON libérées)")
        return perdus

    # ------------------------------------------------------------ réservations
    def reserver(self, robot_id, case_visee):
        """Demande le bail d'une case adjacente. Non bloquant : accord ou refus.

        Le refus n'est jamais une attente : le robot conserve sa case et reste
        dans un état sûr. C'est ce qui interdit tout cycle d'interblocage.
        """
        with self.verrou:
            robot = self.robots.get(robot_id)
            if robot is None:
                return {"accord": False, "motif": "robot non inscrit"}
            if robot.doit_se_recaler:
                return {"accord": False,
                        "motif": f"recalage requis (incertitude "
                                 f"{robot.incertitude:.0f} cm > "
                                 f"{self.seuil_incertitude:.0f} cm)"}

            nom = case_vers_nom(*nom_vers_case(case_visee))
            if nom in robot.baux:
                return {"accord": True, "case": nom, "deja": True}

            voisines = {case_vers_nom(r, c)
                        for r, c in cases_voisines(*nom_vers_case(robot.case))}
            if nom not in voisines:
                return {"accord": False,
                        "motif": f"{nom} n'est pas adjacente à {robot.case}"}

            case = self._case(nom)
            if case["etat"] == QUARANTAINE:
                robot.priorite = min(PRIORITE_MAX, robot.priorite + 1)
                return {"accord": False, "motif": f"{nom} en quarantaine : "
                                                  f"{case['raison']}"}
            if case["etat"] != LIBRE:
                # Contestation : on note l'ancienneté du demandeur pour que la
                # case lui revienne quand elle se libérera (anti-famine).
                robot.priorite = min(PRIORITE_MAX, robot.priorite + 1)
                return {"accord": False,
                        "motif": f"{nom} louée à {case['robot']}",
                        "priorite": robot.priorite}

            # Case libre : on l'accorde au demandeur le plus prioritaire s'il y
            # a d'autres prétendants en attente sur cette case.
            meilleur = self._prioritaire_pour(nom, robot)
            if meilleur is not robot:
                return {"accord": False,
                        "motif": f"{nom} promise à {meilleur.id} (priorité "
                                 f"{meilleur.priorite} > {robot.priorite})"}

            self._attribuer(nom, RESERVEE, robot_id)
            robot.baux.add(nom)
            robot.priorite = 0
            self._noter(f"{robot_id} obtient {nom} (transit depuis {robot.case})")
            return {"accord": True, "case": nom, "baux": sorted(robot.baux)}

    def _prioritaire_pour(self, nom, demandeur):
        """Parmi les robots adjacents à `nom` qui attendent, le plus ancien."""
        pretendants = [demandeur]
        for robot in self.robots.values():
            if robot is demandeur or not robot.vivant or robot.priorite == 0:
                continue
            voisines = {case_vers_nom(r, c)
                        for r, c in cases_voisines(*nom_vers_case(robot.case))}
            if nom in voisines:
                pretendants.append(robot)
        return max(pretendants, key=lambda r: (r.priorite, r.id))

    def liberer(self, robot_id, case_liberee, arrive_en=None):
        """Rend un bail. `arrive_en` confirme la case désormais occupée.

        Un robot ne rend sa case d'origine qu'une fois son arrivée confirmée :
        pendant le transit il détient les deux, donc la frontière qu'il balaie
        est protégée.
        """
        with self.verrou:
            robot = self.robots.get(robot_id)
            if robot is None:
                return {"ok": False, "motif": "robot non inscrit"}

            if arrive_en:
                nom_arrivee = case_vers_nom(*nom_vers_case(arrive_en))
                if nom_arrivee not in robot.baux:
                    return {"ok": False,
                            "motif": f"{nom_arrivee} n'est pas louée à {robot_id}"}
                robot.case = nom_arrivee
                self._attribuer(nom_arrivee, OCCUPEE, robot_id)
                self.explorees.add(nom_arrivee)

            nom = case_vers_nom(*nom_vers_case(case_liberee))
            if nom == robot.case:
                return {"ok": False, "motif": "on ne rend pas la case occupée"}
            if nom in robot.baux:
                robot.baux.discard(nom)
                if self._case(nom)["robot"] == robot_id:
                    self._attribuer(nom, LIBRE, None)
                self._noter(f"{robot_id} rend {nom} (occupe {robot.case})")
            return {"ok": True, "baux": sorted(robot.baux), "case": robot.case}

    # ------------------------------------------------- rétroaction du terrain
    def signaler_blocage(self, robot_id, case_visee, detail=""):
        """Le robot s'est trouvé physiquement bloqué : la case visée est suspecte.

        C'est le chaînon qui manquait complètement : le monde physique corrige
        le modèle. Un obstacle qu'aucun capteur ne voit (robot en panne, câble,
        pied de table) devient une case interdite pour tout le monde.
        """
        with self.verrou:
            robot = self.robots.get(robot_id)
            if robot is None:
                return {"ok": False, "motif": "robot non inscrit"}

            nom = case_vers_nom(*nom_vers_case(case_visee))
            robot.baux.discard(nom)
            self._attribuer(nom, QUARANTAINE, None,
                            raison=f"blocage signalé par {robot_id} : {detail}")
            if robot.cible == nom:
                robot.cible = None
            self._noter(f"{robot_id} bloqué vers {nom} -> quarantaine")
            return {"ok": True, "quarantaine": nom, "case": robot.case}

    def lever_quarantaine(self, case):
        """Lève une quarantaine. Geste volontaire de l'opérateur.

        Une quarantaine n'expire jamais toute seule : rien ne permet au serveur
        de savoir qu'un obstacle qu'il n'a jamais vu a été retiré.
        """
        with self.verrou:
            nom = case_vers_nom(*nom_vers_case(case))
            if self._case(nom)["etat"] != QUARANTAINE:
                return {"ok": False, "motif": f"{nom} n'est pas en quarantaine"}
            self._attribuer(nom, LIBRE, None)
            self._noter(f"quarantaine levée sur {nom}")
            return {"ok": True, "case": nom}

    # ------------------------------------------------------------- drapeaux
    def signaler_drapeau(self, robot_id, drapeau_id, case):
        with self.verrou:
            nom = case_vers_nom(*nom_vers_case(case))
            self.drapeaux[int(drapeau_id)] = nom
            robot = self.robots.get(robot_id)
            if robot is not None:
                robot.drapeaux[int(drapeau_id)] = nom
            self._noter(f"{robot_id} déclare le drapeau {drapeau_id} en {nom}")
            return {"ok": True, "drapeaux": dict(self.drapeaux)}

    # ------------------------------------------------------- plan d'exploration
    def prochaine_cible(self, robot_id):
        """Case voisine vers laquelle avancer, ou None.

        Plan volontairement simple : un parcours en largeur vers la case
        inexplorée la plus proche, en contournant quarantaines et baux d'autrui.
        Il n'a PAS besoin d'être bon : la sûreté ne repose pas sur lui. C'est
        tout l'intérêt de l'architecture — on peut remplacer ce planificateur
        par n'importe quoi sans jamais risquer une collision.
        """
        with self.verrou:
            robot = self.robots.get(robot_id)
            if robot is None or not robot.vivant:
                return None

            depart = robot.case
            interdites = {nom for nom, c in self.cases.items()
                          if c["etat"] == QUARANTAINE
                          or (c["etat"] in (RESERVEE, OCCUPEE)
                              and c["robot"] not in (None, robot_id))}

            vus = {depart}
            file = deque([(depart, [])])
            while file:
                courante, chemin = file.popleft()
                if courante not in self.explorees and chemin:
                    robot.cible = chemin[0]
                    return chemin[0]
                for r, c in cases_voisines(*nom_vers_case(courante)):
                    voisine = case_vers_nom(r, c)
                    if voisine in vus or voisine in interdites:
                        continue
                    vus.add(voisine)
                    file.append((voisine, chemin + [voisine]))

            robot.cible = None
            return None

    # ------------------------------------------------------------------- vues
    def quarantaines(self):
        return {nom: c["raison"] for nom, c in self.cases.items()
                if c["etat"] == QUARANTAINE}

    def carte(self):
        with self.verrou:
            return {
                "cases": {nom: {"etat": c["etat"], "robot": c["robot"],
                                "raison": c["raison"]}
                          for nom, c in self.cases.items()
                          if c["etat"] != LIBRE},
                "robots": [r.etat() for r in self.robots.values()],
                "drapeaux": dict(self.drapeaux),
                "explorees": sorted(self.explorees),
                "quarantaines": self.quarantaines(),
                "journal": list(self.journal)[-30:],
            }

    # -------------------------------------------------------------- invariant
    def verifier_invariant(self):
        """Vérifie l'invariant de sûreté. Doit être vrai après CHAQUE opération.

        Appelée en boucle par le simulateur : c'est la preuve exécutable que la
        stratégie tient sa promesse.
        """
        with self.verrou:
            # 1. une case louée l'est à exactement un robot
            for nom, case in self.cases.items():
                if case["etat"] in (RESERVEE, OCCUPEE):
                    proprietaire = case["robot"]
                    if proprietaire not in self.robots:
                        raise ViolationInvariant(
                            f"{nom} louée à un robot inconnu : {proprietaire}")
                    if nom not in self.robots[proprietaire].baux:
                        raise ViolationInvariant(
                            f"{nom} dit appartenir à {proprietaire}, "
                            f"qui ne le revendique pas")

            # 2. deux robots ne partagent jamais un bail
            for a in self.robots.values():
                for b in self.robots.values():
                    if a.id >= b.id:
                        continue
                    commun = a.baux & b.baux
                    if commun:
                        raise ViolationInvariant(
                            f"COLLISION POSSIBLE : {a.id} et {b.id} détiennent "
                            f"tous deux {sorted(commun)}")

            # 3. un robot vivant occupe une case dont il a le bail
            for robot in self.robots.values():
                if robot.vivant and robot.case not in robot.baux:
                    raise ViolationInvariant(
                        f"{robot.id} est en {robot.case} sans en détenir le bail")

            # 4. une case en quarantaine n'est louée à personne — y compris
            #    aux robots présumés en panne, dont les baux doivent être vidés
            for nom, case in self.cases.items():
                if case["etat"] == QUARANTAINE:
                    for robot in self.robots.values():
                        if nom in robot.baux:
                            raise ViolationInvariant(
                                f"{nom} est en quarantaine mais encore louée à "
                                f"{robot.id} (bail fantôme)")
            return True


# ------------------------------------------------------------------ transport
class Handler(BaseHTTPRequestHandler):
    server_version = "proj103-strategie/1.0"
    arbitre = None

    def log_message(self, format, *args):      # noqa: A002
        pass        # trop verbeux avec N robots qui battent chaque seconde

    def _json(self, donnees, code=200):
        corps = json.dumps(donnees).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(corps)))
        self.end_headers()
        self.wfile.write(corps)

    def do_GET(self):
        chemin = urlparse(self.path).path
        if chemin == "/api/carte":
            return self._json(self.arbitre.carte())
        if chemin == "/api/invariant":
            try:
                self.arbitre.verifier_invariant()
                return self._json({"invariant": "tenu"})
            except ViolationInvariant as e:
                return self._json({"invariant": "ROMPU", "detail": str(e)}, 500)
        return self._json({"erreur": "route inconnue"}, 404)

    def do_POST(self):
        chemin = urlparse(self.path).path
        longueur = int(self.headers.get("Content-Length") or 0)
        try:
            corps = json.loads(self.rfile.read(longueur) or b"{}")
        except json.JSONDecodeError:
            return self._json({"erreur": "corps JSON invalide"}, 400)

        routes = {
            "/api/inscription": lambda c: self.arbitre.inscrire(c["id"], c["case"]),
            "/api/battement": lambda c: self.arbitre.battement(
                c["id"], c.get("case"), c.get("incertitude", 0.0)),
            "/api/reservation": lambda c: self.arbitre.reserver(c["id"], c["case"]),
            "/api/liberation": lambda c: self.arbitre.liberer(
                c["id"], c["case"], c.get("arrive_en")),
            "/api/blocage": lambda c: self.arbitre.signaler_blocage(
                c["id"], c["case"], c.get("detail", "")),
            "/api/drapeau": lambda c: self.arbitre.signaler_drapeau(
                c["id"], c["drapeau"], c["case"]),
            "/api/cible": lambda c: {"case": self.arbitre.prochaine_cible(c["id"])},
            "/api/quarantaine/lever": lambda c: self.arbitre.lever_quarantaine(c["case"]),
        }
        action = routes.get(chemin)
        if action is None:
            return self._json({"erreur": "route inconnue"}, 404)
        try:
            return self._json(action(corps))
        except (KeyError, ValueError) as e:
            return self._json({"erreur": f"requête invalide : {e}"}, 400)


def construire_serveur(port=8080, adresse="0.0.0.0", arbitre=None):
    arbitre = arbitre or Arbitre()
    classe = type("HandlerLie", (Handler,), {"arbitre": arbitre})
    return ThreadingHTTPServer((adresse, port), classe), arbitre


def main():
    analyseur = argparse.ArgumentParser(description="Serveur central de stratégie")
    analyseur.add_argument("--port", type=int, default=8080)
    analyseur.add_argument("--adresse", default="0.0.0.0")
    arguments = analyseur.parse_args()
    serveur, arbitre = construire_serveur(arguments.port, arguments.adresse)
    print(f"[central] arbitrage par baux sur http://{arguments.adresse}:{arguments.port}")
    print(f"[central] carte : /api/carte   invariant : /api/invariant")
    try:
        serveur.serve_forever()
    except KeyboardInterrupt:
        print("\n[central] arrêt")
    finally:
        serveur.server_close()


if __name__ == "__main__":
    main()
