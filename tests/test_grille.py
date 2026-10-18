import pytest

from backend.auxEpreuve import (CaseInvalide, NB_COLONNES, cases_voisines,
                                case_vers_nom, nom_vers_case, row_col_to_x_y,
                                toutes_les_cases, x_y_to_row_col)


def test_aller_retour_exact_sur_les_36_cases():
    for row, col in toutes_les_cases():
        x, y = row_col_to_x_y(row, col)
        assert x_y_to_row_col(x, y) == (row, col), f"{row}{col} -> ({x},{y})"


@pytest.mark.parametrize("y", [250, 275, 299, 300, 350, 10_000])
def test_pas_de_keyerror_sur_les_rangs_hauts(y):
    """La version d'origine levait KeyError: 6 pour y >= 250 cm."""
    row, col = x_y_to_row_col(25, y)
    assert row in "ABCDEF" and 1 <= col <= NB_COLONNES


@pytest.mark.parametrize("x,y", [(-25, -25), (-500, -500), (1000, 1000)])
def test_positions_hors_grille_ramenees_au_bord(x, y):
    row, col = x_y_to_row_col(x, y)
    assert row in "ABCDEF" and 1 <= col <= NB_COLONNES


def test_coins_de_la_grille():
    assert row_col_to_x_y("A", 1) == (25, 275)
    assert row_col_to_x_y("F", 6) == (275, 25)
    assert x_y_to_row_col(25, 275) == ("A", 1)
    assert x_y_to_row_col(275, 25) == ("F", 6)


def test_depart_hors_grille_est_en_f1():
    assert x_y_to_row_col(25, -25) == ("F", 1)


def test_noms_de_case():
    assert case_vers_nom("c", 3) == "C3"
    assert nom_vers_case("C3") == ("C", 3)
    for mauvais in ("", "Z3", "C9", "C", "CC", "33"):
        with pytest.raises(CaseInvalide):
            nom_vers_case(mauvais)


def test_voisines_sans_sortir_de_la_grille():
    assert set(cases_voisines("A", 1)) == {("B", 1), ("A", 2)}
    assert len(cases_voisines("C", 3)) == 4
    assert set(cases_voisines("F", 6)) == {("E", 6), ("F", 5)}
