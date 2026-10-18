#!/usr/bin/env python3
# Outil de calibration : répète un mouvement N fois pour mesurer l'erreur
# cumulée, et en déduire les constantes GAIN_DISTANCE et ENTRAXE_EFFECTIF de
# moteurs/controleMoteurs.py.
#
# Mode d'emploi sur le vrai robot :
#   1. placer le robot sur une marque au sol, noter son orientation
#   2. lancer par exemple :  python3 mesure_actions.py --angle 45 --repetitions 8
#   3. mesurer l'écart RÉEL entre la pose finale et la pose attendue
#   4. corriger la constante correspondante, puis recommencer
#
# L'ancienne version enchaînait 10 rotations de 45° sans rien afficher : il
# fallait deviner ce qu'elle avait mesuré.

import argparse
import asyncio
import sys

from backend import suiviDeplacement
from backend.deplacement import avancer, tourner
from moteurs.controleMoteurs import ErreurDeplacement, RobotController


async def mesurer(robot, angle, distance, repetitions):
    odo = robot.odometrie
    attendu_cap = 0.0
    attendu_dist = 0.0

    for tour in range(1, repetitions + 1):
        if angle:
            await tourner(robot, angle)
            attendu_cap += angle
        if distance:
            await avancer(robot, distance)
            attendu_dist += abs(distance)
        print(f"  {tour:>3}/{repetitions}  cap={odo.cap:>8.2f}°  "
              f"x={odo.x:>7.1f}  y={odo.y:>7.1f}  ±{odo.incertitude:.1f}cm")

    print(f"\ncap cumulé attendu   : {attendu_cap:.2f}°")
    print(f"cap cumulé mesuré    : {attendu_cap - _residu(odo.cap, attendu_cap):.2f}°"
          f"  (odométrie : {odo.cap:.2f}° modulo 360)")
    print(f"distance cumulée     : {attendu_dist:.1f} cm attendus")
    print(f"\nMesurer maintenant l'écart réel au sol, puis ajuster :")
    print(f"  erreur d'angle    -> ENTRAXE_EFFECTIF dans moteurs/controleMoteurs.py")
    print(f"  erreur de distance-> GAIN_DISTANCE dans moteurs/controleMoteurs.py")


def _residu(mesure, attendu):
    return (attendu - mesure + 180) % 360 - 180


def main():
    analyseur = argparse.ArgumentParser(description="Calibration du robot")
    analyseur.add_argument("--angle", type=float, default=45.0,
                           help="rotation par répétition (0 pour n'en faire aucune)")
    analyseur.add_argument("--distance", type=float, default=0.0,
                           help="avance par répétition (0 pour n'en faire aucune)")
    analyseur.add_argument("--repetitions", type=int, default=8)
    analyseur.add_argument("--simulation", action="store_true")
    arguments = analyseur.parse_args()

    if not arguments.angle and not arguments.distance:
        print("rien à mesurer : préciser --angle et/ou --distance", file=sys.stderr)
        return 1

    robot = RobotController(simulation=True if arguments.simulation else None)
    suiviDeplacement.resetState(x=0, y=0, cap=0)
    print(f"{arguments.repetitions} x (angle {arguments.angle}°, "
          f"distance {arguments.distance} cm)\n")
    try:
        asyncio.run(mesurer(robot, arguments.angle, arguments.distance,
                            arguments.repetitions))
    except ErreurDeplacement as e:
        print(f"\nmouvement interrompu : {e}", file=sys.stderr)
        return 1
    finally:
        robot.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
