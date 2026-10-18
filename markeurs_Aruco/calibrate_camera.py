#!/usr/bin/env python3
# Calibration de la caméra sur une mire en échiquier.
#
# Produit la matrice intrinsèque et les coefficients de distorsion à recopier
# dans backend/vision.py.
#
# Deux corrections par rapport à la version d'origine :
#   - le chemin des images était codé en dur sur une machine Windows
#     (C:\Users\HP\Desktop\imag\*.jpg) : la calibration n'était pas
#     reproductible, alors que c'est la donnée dont dépendent toutes les
#     mesures de distance ;
#   - la même boucle de détection des coins était répétée trois fois, ce qui
#     ajoutait chaque image jusqu'à trois fois aux points de calibration et
#     faussait le résultat.
#
#     python3 markeurs_Aruco/calibrate_camera.py 'photos/*.jpg'
#     python3 markeurs_Aruco/calibrate_camera.py 'photos/*.jpg' --cases 6 4 --cote 0.0065

import argparse
import glob
import sys

import numpy as np

CRITERES = None   # initialisé après l'import de cv2


def collecter(images, cases, cote, afficher=False):
    """Points objet/image pour toutes les images où la mire est détectée."""
    import cv2

    criteres = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)
    modele = np.zeros((cases[0] * cases[1], 3), np.float32)
    modele[:, :2] = np.mgrid[0:cases[0], 0:cases[1]].T.reshape(-1, 2)
    modele *= cote

    points_objet, points_image, forme = [], [], None
    for chemin in images:
        image = cv2.imread(chemin)
        if image is None:
            print(f"  illisible : {chemin}", file=sys.stderr)
            continue
        gris = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        forme = gris.shape[::-1]

        trouve, coins = cv2.findChessboardCorners(gris, cases, None)
        if not trouve:
            print(f"  mire non détectée : {chemin}")
            continue

        affines = cv2.cornerSubPix(gris, coins, (11, 11), (-1, -1), criteres)
        points_objet.append(modele)
        points_image.append(affines)
        print(f"  ok : {chemin}")

        if afficher:
            cv2.drawChessboardCorners(image, cases, affines, trouve)
            cv2.imshow("mire", image)
            cv2.waitKey(300)

    if afficher:
        cv2.destroyAllWindows()
    return points_objet, points_image, forme


def main():
    analyseur = argparse.ArgumentParser(description="Calibration de la caméra")
    analyseur.add_argument("motif", help="motif des images, par ex. 'photos/*.jpg'")
    analyseur.add_argument("--cases", type=int, nargs=2, default=(6, 4),
                           metavar=("COLONNES", "LIGNES"),
                           help="nombre de coins internes de la mire")
    analyseur.add_argument("--cote", type=float, default=0.0065,
                           help="côté d'un carré de la mire, en mètres")
    analyseur.add_argument("--afficher", action="store_true")
    arguments = analyseur.parse_args()

    try:
        import cv2
    except ImportError:
        print("OpenCV requis : sudo apt install python3-opencv", file=sys.stderr)
        return 1

    images = sorted(glob.glob(arguments.motif))
    if not images:
        print(f"aucune image pour le motif {arguments.motif!r}", file=sys.stderr)
        return 1
    print(f"{len(images)} image(s) à analyser :")

    points_objet, points_image, forme = collecter(
        images, tuple(arguments.cases), arguments.cote, arguments.afficher)

    if len(points_objet) < 3:
        print(f"\nseulement {len(points_objet)} vue(s) exploitable(s) : "
              f"il en faut au moins 3, idéalement 15 sous des angles variés",
              file=sys.stderr)
        return 1

    erreur, matrice, distorsion, _, _ = cv2.calibrateCamera(
        points_objet, points_image, forme, None, None)

    print(f"\n{len(points_objet)} vues retenues, erreur de reprojection : {erreur:.4f}")
    print("\n# à recopier dans backend/vision.py")
    print(f"CAMERA_MATRIX = np.array({np.array2string(matrice, separator=', ')})")
    print(f"DIST_COEFFS = np.array({np.array2string(distorsion, separator=', ')})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
