import asyncio

import pytest

from backend.auxEpreuve import case_vers_nom, x_y_to_row_col
from backend.autonome import Balayage, itineraire_serpentin
from backend.simu_terrain import CameraSimulee, Terrain
from moteurs.simu import robot_simule


def test_itineraire_serpentin_visite_tout_sans_doublon():
    trajet = itineraire_serpentin()
    assert len(trajet) == 36 and len(set(trajet)) == 36


def test_itineraire_serpentin_alterne_le_sens():
    trajet = itineraire_serpentin(colonnes=(1, 2), rangs=("F", "E"))
    assert trajet == [("F", 1), ("E", 1), ("E", 2), ("F", 2)]


def _jouer(drapeaux, colonnes=(1, 2, 3), rangs=("F", "E", "D"), **kw):
    terrain = Terrain(drapeaux=drapeaux)
    robot, controleur, odo = robot_simule(**kw)
    camera = CameraSimulee(terrain, odo)
    envoyes = []
    balayage = Balayage(robot, camera,
                        envoyer=lambda i, r, c: envoyes.append((i, f"{r}{c}")),
                        journal=lambda *a: None)
    asyncio.run(balayage.executer(itineraire_serpentin(colonnes, rangs)))
    return balayage, envoyes


def test_trouve_tous_les_drapeaux():
    drapeaux = {5: (75, 75), 6: (25, 125), 7: (125, 25), 9: (125, 125)}
    balayage, envoyes = _jouer(drapeaux, bruit=0.03, desequilibre=1.04)
    assert set(balayage.drapeaux_vus) == set(drapeaux)
    assert len(envoyes) == len(drapeaux)


def test_declare_la_case_du_drapeau_et_non_celle_du_robot():
    """L'ancien code déclarait la case d'où le robot APERCEVAIT le drapeau,
    jusqu'à 60 cm de là."""
    drapeaux = {5: (75, 75), 7: (125, 25)}
    balayage, envoyes = _jouer(drapeaux, bruit=0.02, desequilibre=1.02)
    attendu = {i: case_vers_nom(*x_y_to_row_col(*p)) for i, p in drapeaux.items()}
    assert dict(envoyes) == attendu


def test_chaque_drapeau_declare_une_seule_fois():
    balayage, envoyes = _jouer({5: (75, 75)})
    assert len(envoyes) == 1


def test_scan_de_case_referme_toujours_le_tour():
    """Le cap doit revenir à sa valeur de départ, sinon tout le reste du
    balayage part de travers (bug de l'`offset` non réinitialisé)."""
    robot, _, odo = robot_simule(x=25, y=25, cap=0)
    camera = CameraSimulee(Terrain(), odo)
    balayage = Balayage(robot, camera, journal=lambda *a: None)
    asyncio.run(balayage.scanner_case())
    assert abs((odo.cap + 180) % 360 - 180) < 8.0


def test_case_bloquee_est_contournee():
    """Un blocage physique ne doit pas arrêter le balayage."""
    robot, controleur, odo = robot_simule()
    camera = CameraSimulee(Terrain(), odo)
    balayage = Balayage(robot, camera, journal=lambda *a: None)

    appels = {"n": 0}
    reel = robot.move_distance

    async def bloque_une_fois(distance, *a, **k):
        appels["n"] += 1
        if appels["n"] == 2:
            from moteurs.controleMoteurs import RobotBloque
            raise RobotBloque("obstacle simulé")
        return await reel(distance, *a, **k)

    robot.move_distance = bloque_une_fois
    asyncio.run(balayage.executer(itineraire_serpentin((1,), ("F", "E", "D"))))
    assert balayage.cases_bloquees, "la case en échec n'a pas été mémorisée"
    assert balayage.cases_visitees, "le balayage s'est arrêté au premier obstacle"
