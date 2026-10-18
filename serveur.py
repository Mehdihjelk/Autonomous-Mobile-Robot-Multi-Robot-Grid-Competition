#!/usr/bin/env python3

import argparse
import asyncio
import json
import os
import threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from backend import suiviDeplacement
from backend.auxEpreuve import CaseInvalide, case_vers_nom, nom_vers_case
from backend.deplacement import aller_a_case
from moteurs.controleMoteurs import RobotController, ErreurDeplacement

RACINE_WEB = Path(__file__).parent / "website"

# Le mot de passe de la version d'origine était écrit en clair dans le source
# (« TOPSECRETHAHAHA = "bonjour" »). Il vient maintenant de l'environnement.
MOT_DE_PASSE = os.environ.get("PROJ103_MDP", "bonjour")

TYPES_MIME = {".html": "text/html; charset=utf-8",
              ".css": "text/css; charset=utf-8",
              ".js": "application/javascript; charset=utf-8",
              ".svg": "image/svg+xml",
              ".ico": "image/x-icon"}


class BoucleRobot:
    """Exécute les coroutines du robot dans un thread asyncio dédié.

    Le serveur HTTP est multithread et synchrone, les mouvements du robot sont
    asynchrones : cette classe fait le pont. Une seule épreuve à la fois.
    """

    def __init__(self, robot):
        self.robot = robot
        self.boucle = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._tourner, daemon=True)
        self.thread.start()
        self.tache = None
        self.dernier_message = "prêt"
        self.balayage = None

    def _tourner(self):
        asyncio.set_event_loop(self.boucle)
        self.boucle.run_forever()

    @property
    def occupe(self):
        return self.tache is not None and not self.tache.done()

    def lancer(self, coroutine, libelle):
        """Démarre une coroutine si aucune autre n'est en cours."""
        if self.occupe:
            return False, f"déjà occupé : {self.dernier_message}"
        self.dernier_message = libelle
        self.tache = asyncio.run_coroutine_threadsafe(
            self._surveiller(coroutine, libelle), self.boucle)
        return True, libelle

    async def _surveiller(self, coroutine, libelle):
        try:
            resultat = await coroutine
            self.dernier_message = f"{libelle} : terminé"
            return resultat
        except ErreurDeplacement as e:
            # Blocage ou dépassement de durée : on le remonte à l'interface au
            # lieu de laisser le robot pousser contre l'obstacle.
            self.dernier_message = f"{libelle} : INTERROMPU ({e})"
            self.robot.stop()
        except Exception as e:                       # noqa: BLE001
            self.dernier_message = f"{libelle} : erreur ({e})"
            self.robot.stop()

    def arreter(self):
        if self.occupe:
            self.tache.cancel()
        self.robot.stop()
        self.dernier_message = "arrêt demandé"


class Handler(BaseHTTPRequestHandler):
    server_version = "proj103-team1/2.0"
    robot = None
    boucle = None

    def log_message(self, format, *args):       # noqa: A002
        print(f"[web] {self.address_string()} {format % args}")

    # ------------------------------------------------------------------ sorties
    def _repondre(self, code, corps=b"", type_mime="text/plain; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", type_mime)
        self.send_header("Content-Length", str(len(corps)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(corps)

    def _json(self, donnees, code=200):
        self._repondre(code, json.dumps(donnees).encode(), "application/json")

    # -------------------------------------------------------------------- GET
    def do_GET(self):
        chemin = urlparse(self.path).path
        if chemin == "/api/etat":
            return self._json(self._etat())
        return self._servir_fichier(chemin)

    def do_HEAD(self):
        self.do_GET()

    def _servir_fichier(self, chemin):
        relatif = "index.html" if chemin in ("/", "") else chemin.lstrip("/")
        cible = (RACINE_WEB / relatif).resolve()
        # Pas d'évasion hors du dossier website/
        if not str(cible).startswith(str(RACINE_WEB.resolve())) or not cible.is_file():
            return self._repondre(404, b"introuvable")
        type_mime = TYPES_MIME.get(cible.suffix, "application/octet-stream")
        self._repondre(200, cible.read_bytes(), type_mime)

    def _etat(self):
        odo = self.robot.odometrie
        row, col = odo.case
        balayage = self.boucle.balayage
        return {
            "x": round(odo.x, 1),
            "y": round(odo.y, 1),
            "cap": round(odo.cap, 1),
            "case": case_vers_nom(row, col),
            "incertitude": round(odo.incertitude, 1),
            "occupe": self.boucle.occupe,
            "message": self.boucle.dernier_message,
            "simulation": self.robot.simule,
            "drapeaux": balayage.drapeaux_vus if balayage else {},
            "cases_bloquees": sorted(balayage.cases_bloquees) if balayage else [],
        }

    # ------------------------------------------------------------------- POST
    def do_POST(self):
        url = urlparse(self.path)
        parametres = parse_qs(url.query)

        # Exigence de tests_projet.sh : arrêt propre du serveur.
        if parametres.get("param", [None])[0] == "exit":
            self._repondre(200, b"arret du serveur\n")
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return

        corps = {}
        longueur = int(self.headers.get("Content-Length") or 0)
        if longueur:
            brut = self.rfile.read(longueur)
            try:
                corps = json.loads(brut)
            except json.JSONDecodeError:
                corps = {cle: v[0] for cle, v in parse_qs(brut.decode()).items()}

        if corps.get("mdp") != MOT_DE_PASSE:
            return self._json({"erreur": "mot de passe invalide"}, 403)

        routes = {
            "/api/move": self._move,
            "/api/epreuve": self._epreuve,
            "/api/case": self._case,
            "/api/stop": self._stop,
        }
        action = routes.get(url.path)
        if action is None:
            return self._repondre(404, b"route inconnue")
        return action(corps)

    # ----------------------------------------------------------------- actions
    def _move(self, corps):
        """Pilotage manuel : une impulsion par requête."""
        direction = corps.get("direction", "Stop")
        if self.boucle.occupe and direction != "Stop":
            return self._json({"erreur": "une épreuve est en cours"}, 409)
        try:
            self.robot.move(direction)
        except ValueError as e:
            return self._json({"erreur": str(e)}, 400)
        return self._json({"ok": True, "direction": direction})

    def _epreuve(self, corps):
        from backend.autonome import Balayage, itineraire_serpentin
        from backend.vision import Camera

        numero = int(corps.get("epreuve", 0))
        try:
            camera = corps.get("_camera") or Camera()
        except RuntimeError as e:
            return self._json({"erreur": str(e)}, 503)

        suiviDeplacement.resetState()
        self.boucle.balayage = Balayage(self.robot, camera)
        itineraire = (itineraire_serpentin(colonnes=(5, 6)) if numero == 0
                      else itineraire_serpentin())
        libelle = f"balayage {'2 dernières colonnes' if numero == 0 else 'grille complète'}"
        ok, message = self.boucle.lancer(
            self.boucle.balayage.executer(itineraire), libelle)
        return self._json({"ok": ok, "message": message}, 200 if ok else 409)

    def _case(self, corps):
        """Rejoint une case donnée, par exemple « C3 »."""
        try:
            row, column = nom_vers_case(corps.get("case", ""))
        except CaseInvalide as e:
            return self._json({"erreur": str(e)}, 400)
        ok, message = self.boucle.lancer(
            aller_a_case(self.robot, row, column), f"rejoindre {row}{column}")
        return self._json({"ok": ok, "message": message}, 200 if ok else 409)

    def _stop(self, corps):
        self.boucle.arreter()
        return self._json({"ok": True})


def construire_serveur(port=8080, adresse="localhost", simulation=None, robot=None):
    """Prépare le serveur HTTP. Renvoie (serveur, robot)."""
    robot = robot or RobotController(simulation=simulation)
    boucle = BoucleRobot(robot)

    classe = type("HandlerLie", (Handler,), {"robot": robot, "boucle": boucle})
    serveur = ThreadingHTTPServer((adresse, port), classe)
    return serveur, robot


def main():
    analyseur = argparse.ArgumentParser(description="Serveur de contrôle du robot")
    analyseur.add_argument("--port", type=int, default=8080)
    analyseur.add_argument("--adresse", default="localhost",
                           help="0.0.0.0 pour être joignable depuis le réseau")
    analyseur.add_argument("--simulation", action="store_true",
                           help="forcer le contrôleur moteurs simulé")
    arguments = analyseur.parse_args()

    serveur, robot = construire_serveur(
        arguments.port, arguments.adresse,
        simulation=True if arguments.simulation else None)
    print(f"[web] interface sur http://{arguments.adresse}:{arguments.port}/index.html")
    print(f"[web] mot de passe : {'(défaut)' if 'PROJ103_MDP' not in os.environ else '(variable PROJ103_MDP)'}")
    print(f"[web] moteurs : {'simulés' if robot.simule else 'carte I2C'}")
    try:
        serveur.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        robot.stop()
        serveur.server_close()
        print("[web] serveur arrêté")


if __name__ == "__main__":
    main()
