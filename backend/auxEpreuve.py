COTE_CASE = 50          # cm
NB_RANGS = 6
NB_COLONNES = 6
COTE_GRILLE = COTE_CASE * NB_RANGS   # 300 cm

RANGS = ("F", "E", "D", "C", "B", "A")   # indexé par int_row : 0 -> F, 5 -> A

dico_row = {lettre: i for i, lettre in enumerate(RANGS)}      # "A" -> 5
dico_letter = {i: lettre for i, lettre in enumerate(RANGS)}   # 5   -> "A"


class CaseInvalide(ValueError):
    """Case hors grille ou mal formée."""


def _borner(valeur, mini, maxi):
    return max(mini, min(maxi, valeur))


def row_col_to_x_y(row, column):
    """Centre de la case (row, column) en cm. `column` est 1-based.

    >>> row_col_to_x_y("A", 1)
    (25, 275)
    >>> row_col_to_x_y("F", 6)
    (275, 25)
    """
    row = str(row).upper()
    if row not in dico_row:
        raise CaseInvalide(f"rang inconnu : {row!r} (attendu A-F)")
    column = int(column)
    if not 1 <= column <= NB_COLONNES:
        raise CaseInvalide(f"colonne hors grille : {column} (attendu 1-{NB_COLONNES})")

    x = COTE_CASE * (column - 1) + COTE_CASE // 2
    y = COTE_CASE * dico_row[row] + COTE_CASE // 2
    return (x, y)


def x_y_to_row_col(x, y):
    """Case contenant le point (x, y). Réciproque exacte de row_col_to_x_y.

    Les positions hors grille sont ramenées à la case de bord la plus proche :
    l'odométrie dérive et le robot démarre en y = -25, donc lever une exception
    ici reviendrait à faire planter le robot en pleine épreuve.

    >>> x_y_to_row_col(25, 275)
    ('A', 1)
    >>> x_y_to_row_col(275, 25)
    ('F', 6)
    >>> x_y_to_row_col(25, -25)      # position de départ, hors grille
    ('F', 1)
    """
    colonne = _borner(int(x // COTE_CASE) + 1, 1, NB_COLONNES)
    int_row = _borner(int(y // COTE_CASE), 0, NB_RANGS - 1)
    return (dico_letter[int_row], colonne)


def case_vers_nom(row, column):
    """('C', 3) -> 'C3'"""
    return f"{str(row).upper()}{int(column)}"


def nom_vers_case(nom):
    """'C3' -> ('C', 3). Lève CaseInvalide si le format est mauvais."""
    nom = str(nom).strip().upper()
    if len(nom) != 2 or nom[0] not in dico_row or not nom[1].isdigit():
        raise CaseInvalide(f"case mal formée : {nom!r} (attendu par ex. 'C3')")
    colonne = int(nom[1])
    if not 1 <= colonne <= NB_COLONNES:
        raise CaseInvalide(f"colonne hors grille : {nom!r}")
    return (nom[0], colonne)


def cases_voisines(row, column):
    """Les 4 cases adjacentes (sans diagonales) restant dans la grille."""
    int_row = dico_row[str(row).upper()]
    colonne = int(column)
    voisines = []
    for d_row, d_col in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        r, c = int_row + d_row, colonne + d_col
        if 0 <= r < NB_RANGS and 1 <= c <= NB_COLONNES:
            voisines.append((dico_letter[r], c))
    return voisines


def toutes_les_cases():
    """Les 36 cases de la grille, de A1 à F6."""
    return [(lettre, col)
            for lettre in reversed(RANGS)
            for col in range(1, NB_COLONNES + 1)]
