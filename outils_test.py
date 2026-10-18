#!/usr/bin/env python3

import argparse
import asyncio
import sys
from urllib.parse import urlparse

from backend import suiviDeplacement
from backend.auxEpreuve import x_y_to_row_col
from backend.deplacement import avancer, tourner
from moteurs.controleMoteurs import ErreurDeplacement, RobotController


# --------------------------------------------------------------------- moteur
def analyser_sequence(texte):
    """« r50,a45,r-50 » -> [('r', 50.0), ('a', 45.0), ('r', -50.0)].

    rDIST : déplacement rectilinéaire de DIST cm (négatif = recule)
    aANG  : rotation sur place de ANG degrés (positif = vers la droite)
    """
    actions = []
    for brut in texte.split(","):
        element = brut.strip()
        if not element:
            continue
        nature, valeur = element[0].lower(), element[1:]
        if nature not in ("r", "a"):
            raise ValueError(f"action inconnue : {element!r} (attendu rDIST ou aANG)")
        try:
            actions.append((nature, float(valeur)))
        except ValueError:
            raise ValueError(f"valeur illisible : {element!r}") from None
    if not actions:
        raise ValueError("séquence vide")
    return actions


async def _executer_moteur(actions, robot):
    for nature, valeur in actions:
        if nature == "r":
            await avancer(robot, valeur)
        else:
            await tourner(robot, valeur)
    robot.stop()


def commande_moteur(arguments):
    try:
        actions = analyser_sequence(arguments.sequence)
    except ValueError as e:
        print(f"erreur : {e}", file=sys.stderr)
        return 1

    robot = RobotController(simulation=True if arguments.simulation else None)
    print(f"séquence : {' puis '.join(f'{n}{v:g}' for n, v in actions)}")
    try:
        asyncio.run(_executer_moteur(actions, robot))
    except ErreurDeplacement as e:
        print(f"mouvement interrompu : {e}", file=sys.stderr)
        robot.stop()
        return 1
    odo = robot.odometrie
    row, col = odo.case
    print(f"pose finale : x={odo.x:.1f} cm  y={odo.y:.1f} cm  "
          f"cap={odo.cap:.1f}°  case={row}{col}")
    return 0


# --------------------------------------------------------------------- caméra
def commande_camera(arguments):
    """Une ligne par marqueur détecté : « ID x y dist angle »."""
    from backend.vision import detections_dans_fichier
    try:
        detections = detections_dans_fichier(arguments.image)
    except (RuntimeError, FileNotFoundError) as e:
        print(f"erreur : {e}", file=sys.stderr)
        return 1
    for detection in sorted(detections, key=lambda d: d.id):
        print(detection.ligne())
    return 0


# ---------------------------------------------------------------------- suivi
def commande_suivi(arguments):
    """Envoie une position puis une capture de drapeau au serveur de suivi.

    row et col sont déduits de POS_X et POS_Y, comme l'exige l'énoncé.
    """
    url = urlparse(arguments.serveur if "//" in arguments.serveur
                   else f"http://{arguments.serveur}")
    suiviDeplacement.addresseServeurSuivi = url.netloc or url.path.strip("/")
    # Cette commande a pour objet même de parler au serveur : on émet.
    suiviDeplacement.activer(True)
    print(f"serveur de suivi : {suiviDeplacement.addresseServeurSuivi}")

    suiviDeplacement.resetState(x=arguments.pos_x, y=arguments.pos_y, cap=0)
    position_ok = suiviDeplacement.sendPosition()
    print(f"position ({arguments.pos_x}, {arguments.pos_y}) : "
          f"{'envoyée' if position_ok else 'ÉCHEC'}")

    row, col = x_y_to_row_col(arguments.pos_x, arguments.pos_y)
    marqueur_ok = suiviDeplacement.sendMarkerPosition(arguments.marqueur, row, col)
    print(f"marqueur {arguments.marqueur} en {row}{col} : "
          f"{'envoyé' if marqueur_ok else 'ÉCHEC'}")
    return 0 if (position_ok and marqueur_ok) else 1


# ----------------------------------------------------------------------- main
def main():
    analyseur = argparse.ArgumentParser(
        description="Points d'entrée appelés par tests_projet.sh")
    analyseur.add_argument("--simulation", action="store_true",
                           help="forcer les moteurs simulés")
    sous = analyseur.add_subparsers(dest="commande", required=True)

    p_moteur = sous.add_parser("moteur", help="exécuter une séquence de mouvements")
    p_moteur.add_argument("sequence")
    p_moteur.set_defaults(fonction=commande_moteur)

    p_camera = sous.add_parser("camera", help="détecter les marqueurs d'une image")
    p_camera.add_argument("image")
    p_camera.set_defaults(fonction=commande_camera)

    p_suivi = sous.add_parser("suivi", help="tester les API du serveur de suivi")
    p_suivi.add_argument("serveur")
    p_suivi.add_argument("pos_x", type=float)
    p_suivi.add_argument("pos_y", type=float)
    p_suivi.add_argument("marqueur", type=int)
    p_suivi.set_defaults(fonction=commande_suivi)

    arguments = analyseur.parse_args()
    return arguments.fonction(arguments)


if __name__ == "__main__":
    sys.exit(main())
