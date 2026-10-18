#!/usr/bin/env python3
# Affiche en direct les marqueurs vus par la caméra, avec distance et angle.
#
# Remplace calcul_dist.py, calcul_dist_angle.py et
# calcul_dist_angle_prototype.py, qui étaient trois quasi-doublons du même
# script (deux d'entre eux ne différaient que par un commentaire). Toute la
# géométrie vit désormais dans backend/vision.py.
#
#     python3 markeurs_Aruco/visualiser.py
#     python3 markeurs_Aruco/visualiser.py --image photo.jpg

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.vision import (CAMERA_MATRIX, DIST_COEFFS, detections_dans_fichier,
                            detections_dans_image)


def afficher(detections):
    if not detections:
        print("aucun marqueur détecté")
        return
    print(f"{'ID':>4} {'nature':>9} {'dist(cm)':>9} {'angle(°)':>9} "
          f"{'x(px)':>7} {'y(px)':>7}")
    for d in sorted(detections, key=lambda d: d.distance_cm):
        nature = "repère" if d.est_repere else "drapeau"
        print(f"{d.id:>4} {nature:>9} {d.distance_cm:>9.1f} {d.angle_deg:>9.1f} "
              f"{d.x_px:>7.0f} {d.y_px:>7.0f}")


def flux_direct():
    import cv2
    capture = cv2.VideoCapture(0, getattr(cv2, "CAP_V4L", 0))
    if not capture.isOpened():
        print("caméra inaccessible", file=sys.stderr)
        return 1
    print("q pour quitter")
    try:
        while True:
            ok, image = capture.read()
            if not ok:
                print("lecture impossible", file=sys.stderr)
                break
            detections = detections_dans_image(image)
            for d in detections:
                cv2.putText(image, f"{d.id}: {d.distance_cm:.0f}cm {d.angle_deg:+.0f}deg",
                            (10, 30 + 25 * detections.index(d)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
            cv2.imshow("marqueurs ArUco", image)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        capture.release()
        cv2.destroyAllWindows()
    return 0


def main():
    analyseur = argparse.ArgumentParser(
        description="Visualiser les marqueurs ArUco vus par la caméra")
    analyseur.add_argument("--image", help="analyser un fichier au lieu du flux")
    arguments = analyseur.parse_args()

    if arguments.image:
        afficher(detections_dans_fichier(arguments.image))
        return 0
    return flux_direct()


if __name__ == "__main__":
    sys.exit(main())
