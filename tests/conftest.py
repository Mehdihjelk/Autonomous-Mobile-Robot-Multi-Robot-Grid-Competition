import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

import pytest

from backend import suiviDeplacement


# Aucun test ne doit contacter le serveur de suivi de l'école.
suiviDeplacement.activer(False)


@pytest.fixture(autouse=True)
def odometrie_propre():
    """Remet le singleton d'odométrie à zéro entre chaque test."""
    suiviDeplacement.resetState()
    yield
    suiviDeplacement.resetState()


@pytest.fixture
def robot():
    """Robot simulé, horloge virtuelle, sans attente réelle."""
    from moteurs.simu import robot_simule
    r, controleur, odometrie = robot_simule(x=0, y=0, cap=0)
    return r, controleur, odometrie
