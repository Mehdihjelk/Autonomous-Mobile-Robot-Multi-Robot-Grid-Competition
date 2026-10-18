import pytest

from outils_test import analyser_sequence


def test_sequence_du_sujet():
    assert analyser_sequence("r50,a45,r-50,a90,r50") == [
        ("r", 50.0), ("a", 45.0), ("r", -50.0), ("a", 90.0), ("r", 50.0)]


def test_espaces_et_casse_toleres():
    assert analyser_sequence(" R50 , A-45 ") == [("r", 50.0), ("a", -45.0)]


@pytest.mark.parametrize("mauvais", ["", "x12", "r", "rabc", ","])
def test_sequences_invalides(mauvais):
    with pytest.raises(ValueError):
        analyser_sequence(mauvais)


@pytest.mark.parametrize("tolere", ["a1,,", "r50,", ",r50", " r50 , "])
def test_virgules_superflues_tolerees(tolere):
    """Mieux vaut accepter une virgule en trop que de faire échouer un test
    de notation sur un détail de formatage."""
    assert analyser_sequence(tolere)


def test_decimales_acceptees():
    assert analyser_sequence("r12.5,a0.5") == [("r", 12.5), ("a", 0.5)]
