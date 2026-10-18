import asyncio
import math

import pytest

from backend.deplacement import aller_a, aller_a_case, avancer, tourner


def executer(c):
    return asyncio.run(c)


@pytest.mark.parametrize("angle", [90, 180, 270, 360, 720, -90, -180, -270, -360])
def test_rotations_sans_tour_parasite(robot, angle):
    """Un cap cible non normalisé faisait sauter le reste de 360° à ±180°,
    et le robot effectuait des tours complets en trop."""
    r, controleur, _ = robot
    executer(tourner(r, angle))
    _, _, cap_reel = controleur.pose_reelle
    tourne = controleur.pose_reelle[2]
    attendu = (angle + 180) % 360 - 180
    assert ((tourne - attendu + 180) % 360 - 180) == pytest.approx(0, abs=1.5)


@pytest.mark.parametrize("distance", [50, 120, 300, -75])
def test_distances_precises_quel_que_soit_le_nombre_de_pas(robot, distance):
    """L'ancien `avancer` incrémentait un compteur de 50 en dur, sans jamais
    regarder la position réelle : l'erreur s'accumulait à chaque pas."""
    r, _, _ = robot
    parcouru = executer(avancer(r, distance))
    assert parcouru == pytest.approx(distance, abs=1.0)


def test_pas_jamais_superieur_a_une_case(robot):
    """Borne la dérive : jamais plus de 50 cm ni 90° d'un coup."""
    r, _, _ = robot
    demandes = []
    original = r.move_distance

    async def espion(distance, *a, **k):
        demandes.append(abs(distance))
        return await original(distance, *a, **k)

    r.move_distance = espion
    executer(avancer(r, 300))
    assert demandes and max(demandes) <= 50.0 + 1e-6


def test_carre_revient_au_point_de_depart(robot):
    r, _, odo = robot

    async def carre():
        for _ in range(4):
            await avancer(r, 50)
            await tourner(r, 90)

    executer(carre())
    assert math.hypot(odo.x, odo.y) < 3.0
    assert abs((odo.cap + 180) % 360 - 180) < 4.0


def test_aller_a_atteint_le_point(robot):
    r, _, odo = robot
    executer(aller_a(r, 100, 150))
    assert math.dist((odo.x, odo.y), (100, 150)) < 3.0


def test_aller_a_case_atteint_la_bonne_case():
    from backend import suiviDeplacement
    from moteurs.simu import robot_simule
    r, _, odo = robot_simule()
    for case in [("F", 1), ("D", 3), ("A", 6), ("F", 6)]:
        executer(aller_a_case(r, *case))
        assert odo.case == case, f"visé {case}, cru en {odo.case}"


def test_bruit_et_desequilibre_moteur_restent_tolerables():
    """Avec 8 % de bruit et 10 % de déséquilibre, la boucle fermée tient."""
    from moteurs.simu import robot_simule
    r, _, odo = robot_simule(bruit=0.08, desequilibre=1.10, x=0, y=0, cap=0)
    executer(tourner(r, 90))
    assert odo.cap == pytest.approx(90, abs=2.0)
