import math

import pytest

from backend.vision import (Detection, MARQUEURS_REPERES, interessant, mesurer,
                            position_marqueur, pose_depuis_repere,
                            taille_marqueur)
import backend.vision as vision


def test_taille_depend_de_lidentifiant():
    """L'ancien code appliquait 11 mm à tous les marqueurs, y compris aux
    repères fixes de 48 mm : distance sous-estimée d'un facteur ~4,4."""
    for identifiant in MARQUEURS_REPERES:
        assert taille_marqueur(identifiant) == 0.048
    for identifiant in (0, 5, 6, 9):
        assert taille_marqueur(identifiant) == 0.011


def test_marqueur_a_droite_a_un_angle_negatif():
    """Sens trigonométrique, comme l'exige tests_projet.sh."""
    droite = mesurer(6, (0.3, 0, 1.0), (600, 375), (800, 750))
    gauche = mesurer(6, (-0.3, 0, 1.0), (200, 375), (800, 750))
    assert droite.angle_deg < 0 < gauche.angle_deg
    assert droite.angle_deg == pytest.approx(-gauche.angle_deg)


def test_angle_sans_le_facteur_2_parasite():
    """L'ancien code calculait 2*atan2(x, z) sans raison."""
    detection = mesurer(6, (1.0, 0, 1.0), (400, 375), (800, 750))
    assert abs(detection.angle_deg) == pytest.approx(45.0, abs=0.01)


def test_pixels_y_vers_le_haut():
    haut = mesurer(6, (0, 0, 1.0), (400, 100), (800, 750))
    bas = mesurer(6, (0, 0, 1.0), (400, 650), (800, 750))
    assert haut.y_px > 0 > bas.y_px


def test_format_de_ligne():
    detection = mesurer(6, (0, 0, 1.2), (400, 375), (800, 750))
    champs = detection.ligne().split()
    assert len(champs) == 5
    assert champs[0] == "6" and champs[3] == "120"
    assert "-0" not in champs      # pas de zéro négatif


def test_filtre_des_drapeaux():
    assert interessant(Detection(6, 0, 0, 45, 0))
    assert not interessant(Detection(6, 0, 0, 95, 0)), "hors de portée utile"
    assert not interessant(Detection(2, 0, 0, 30, 0)), "repère fixe, pas un drapeau"


def test_recalage_est_la_reciproque_de_la_mesure():
    """Non-régression : le recalage utilisait la normale du marqueur au lieu du
    cap du robot, et appliquait des corrections de 90 cm."""
    vision.REPERES_FIXES.clear()
    vision.REPERES_FIXES[1] = (150.0, 300.0)
    try:
        x_robot, y_robot, cap = 120.0, 250.0, 30.0
        dx, dy = 150.0 - x_robot, 300.0 - y_robot
        azimut = math.degrees(math.atan2(dx, dy))
        detection = Detection(1, 0, 0, math.hypot(dx, dy), -(azimut - cap))

        retrouve = pose_depuis_repere(detection, cap)
        assert retrouve[0] == pytest.approx(x_robot, abs=0.01)
        assert retrouve[1] == pytest.approx(y_robot, abs=0.01)
    finally:
        vision.REPERES_FIXES.clear()


def test_position_marqueur_est_la_reciproque():
    detection = Detection(6, 0, 0, 50.0, -30.0)
    x, y = position_marqueur(detection, 100.0, 100.0, 20.0)
    assert math.hypot(x - 100.0, y - 100.0) == pytest.approx(50.0, abs=0.01)
