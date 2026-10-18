import math

from backend.suiviDeplacement import (DERIVE_PAR_CM, INCERTITUDE_RECALAGE,
                                      Odometrie)


def test_cap_zero_avance_vers_le_nord():
    odo = Odometrie(x=0, y=0, cap=0)
    odo.avancer(50)
    assert odo.position == (0.0, 50.0)


def test_cap_90_avance_vers_lest():
    """Convention imposée par tests_projet.sh : angle positif = vers la droite."""
    odo = Odometrie(x=0, y=0, cap=0)
    odo.tourner(90)
    odo.avancer(50)
    assert math.isclose(odo.x, 50.0, abs_tol=1e-9)
    assert math.isclose(odo.y, 0.0, abs_tol=1e-9)


def test_cap_normalise_dans_moins_180_180():
    odo = Odometrie(cap=0)
    odo.tourner(270)
    assert -180 < odo.cap <= 180
    odo.tourner(-540)
    assert -180 < odo.cap <= 180


def test_incertitude_croit_avec_la_distance():
    odo = Odometrie()
    depart = odo.incertitude
    odo.avancer(100)
    assert odo.incertitude == depart + 100 * DERIVE_PAR_CM


def test_recalage_reduit_lincertitude():
    odo = Odometrie()
    odo.avancer(1000)
    assert odo.incertitude > 10
    odo.recaler(100, 100)
    assert odo.incertitude == INCERTITUDE_RECALAGE
    assert odo.position == (100.0, 100.0)
