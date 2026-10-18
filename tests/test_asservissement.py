import asyncio

import pytest

from moteurs.controleMoteurs import MouvementTropLong, RobotBloque


def executer(coroutine):
    return asyncio.run(coroutine)


# ------------------------------------------------------------- conversions
@pytest.mark.parametrize("distance", [0.25, 1, 7.5, 50, -50, 100, 300])
def test_conversions_distance_reciproques(robot, distance):
    """Non-régression du bug n°8 : calibration appliquée dans un seul sens."""
    r, _, _ = robot
    assert r.ticks_to_distance(r.distance_to_ticks(distance)) == pytest.approx(
        distance, abs=0.02)


@pytest.mark.parametrize("angle", [1, 45, 90, -90, 180, 360])
def test_conversions_angle_reciproques(robot, angle):
    r, _, _ = robot
    assert r.ticks_to_angle(r.angle_to_ticks(angle)) == pytest.approx(angle, abs=0.05)


# --------------------------------------------------------------- odométrie
def test_odometrie_suit_la_verite_terrain(robot):
    """Non-régression du bug n°1 : l'odométrie n'était jamais mise à jour."""
    r, controleur, odo = robot

    async def parcours():
        await r.move_distance(50)
        await r.tourne_angle(90)
        await r.move_distance(100)

    executer(parcours())
    vrai_x, vrai_y, _ = controleur.pose_reelle
    assert odo.x == pytest.approx(vrai_x, abs=0.5)
    assert odo.y == pytest.approx(vrai_y, abs=0.5)
    assert odo.x != 0 or odo.y != 0, "la pose n'a pas bougé du tout"


def test_pas_de_double_comptage_sur_le_chemin_de_production():
    """Non-régression du bug n°9 : l'odométrie était comptée deux fois.

    Le piège n'apparaissait QUE dans la configuration par défaut, où
    l'odométrie du robot est le singleton de suiviDeplacement — c'est-à-dire
    exactement en production.
    """
    from backend import suiviDeplacement
    from backend.deplacement import tourner
    from moteurs.controleMoteurs import RobotController

    r = RobotController(simulation=True)
    r.periode = 0
    r.horloge = lambda: r.controller.temps
    assert r.odometrie is suiviDeplacement.odometrie

    suiviDeplacement.resetState(x=0, y=0, cap=0)
    executer(tourner(r, 90))
    assert r.odometrie.cap == pytest.approx(90, abs=1.5)


# ----------------------------------------------------------------- sécurité
def test_blocage_leve_une_exception_et_arrete_les_moteurs(robot):
    """Non-régression du pire mode de défaillance : pousser indéfiniment."""
    r, controleur, _ = robot

    async def bloquer_en_route():
        tache = asyncio.ensure_future(r.move_distance(300))
        for _ in range(40):
            await asyncio.sleep(0)
        controleur.bloquer()
        await tache

    with pytest.raises(RobotBloque):
        executer(bloquer_en_route())
    assert controleur.get_motor_speed() == (0, 0)


def test_blocage_immediat_detecte(robot):
    r, controleur, _ = robot
    controleur.bloquer()
    with pytest.raises(RobotBloque):
        executer(r.move_distance(50))
    assert controleur.get_motor_speed() == (0, 0)


def test_duree_bornee(robot):
    """Un mouvement qui n'avance qu'au ralenti finit par être abandonné."""
    r, controleur, _ = robot
    r.fenetre_blocage = 1e9        # on neutralise la détection de blocage
    r.marge_duree = 0.2            # budget volontairement intenable
    r.duree_min = 0.05
    with pytest.raises(MouvementTropLong):
        executer(r.move_distance(300))
    assert controleur.get_motor_speed() == (0, 0)


def test_mouvement_nul_ne_fait_rien(robot):
    r, controleur, odo = robot
    executer(r.move_distance(0))
    assert (odo.x, odo.y) == (0.0, 0.0)
