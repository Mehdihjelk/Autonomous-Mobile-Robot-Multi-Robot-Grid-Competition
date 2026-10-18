#!/usr/bin/env python3

import argparse
import asyncio
import sys

from backend import suiviDeplacement
from moteurs.controleMoteurs import RobotController

CENTRAL_DEFAUT = "http://127.0.0.1:8080"


def ouvrir_camera(simulation=False):
    """Caméra réelle, ou caméra simulée sur un terrain fictif en simulation."""
    if simulation:
        from backend.simu_terrain import Terrain, CameraSimulee
        terrain = Terrain(drapeaux={5: (75, 75), 6: (25, 175), 7: (225, 25)})
        return CameraSimulee(terrain, suiviDeplacement.odometrie)
    from backend.vision import Camera
    try:
        return Camera()
    except RuntimeError as e:
        print(f"[client] caméra indisponible ({e})")
        return None


async def mode_coordonne(robot, camera, adresse, robot_id, cycles=None):
    """Mode de groupe : client du serveur central de stratégie."""
    from strategie.client_strategie import ClientStrategie
    client = ClientStrategie(robot, camera, serveur=adresse, robot_id=robot_id)
    if not client.joignable():
        return False
    print(f"[client] serveur central joignable sur {adresse} -> mode COORDONNÉ")
    await client.boucle(cycles=cycles)
    return True


async def mode_autonome(robot, camera, itineraire=None):
    """Mode solitaire : balayage de la grille sans coordination."""
    from backend.autonome import Balayage, itineraire_serpentin
    print("[client] mode AUTONOME : balayage de la grille")
    balayage = Balayage(robot, camera)
    return await balayage.executer(itineraire or itineraire_serpentin())


async def executer(arguments):
    suiviDeplacement.activer(arguments.suivi and not arguments.simulation)
    if not suiviDeplacement.ACTIF:
        print("[client] serveur de suivi : HORS LIGNE (--suivi pour émettre)")
    robot = RobotController(simulation=True if arguments.simulation else None)
    camera = ouvrir_camera(arguments.simulation)
    if camera is None:
        print("[client] pas de caméra : aucun drapeau ne pourra être détecté")
        return 1

    suiviDeplacement.resetState()
    try:
        if not arguments.autonome:
            if await mode_coordonne(robot, camera, arguments.central,
                                    arguments.id, arguments.cycles):
                return 0
            print(f"[client] {arguments.central} ne répond pas -> repli en autonome")
        await mode_autonome(robot, camera)
        return 0
    except KeyboardInterrupt:
        print("\n[client] interruption")
        return 0
    finally:
        robot.stop()
        robot.stop_sending_coordinates()
        camera.liberer()


def main():
    analyseur = argparse.ArgumentParser(description="Robot team1 — client")
    analyseur.add_argument("--central", default=CENTRAL_DEFAUT,
                           help="adresse du serveur central de stratégie")
    analyseur.add_argument("--id", default="team1", help="identifiant du robot")
    analyseur.add_argument("--autonome", action="store_true",
                           help="ne pas tenter le mode coordonné")
    analyseur.add_argument("--simulation", action="store_true",
                           help="moteurs et caméra simulés")
    analyseur.add_argument("--cycles", type=int, default=None,
                           help="nombre de cycles en mode coordonné (défaut : illimité)")
    analyseur.add_argument("--suivi", action="store_true",
                           help="émettre réellement vers le serveur de suivi de "
                                "l'école (désactivé par défaut)")
    return asyncio.run(executer(analyseur.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
