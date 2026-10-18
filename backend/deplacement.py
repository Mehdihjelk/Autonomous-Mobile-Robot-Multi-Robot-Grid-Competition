import math

PAS_DISTANCE = 50.0     # cm, soit une case
PAS_ANGLE = 90.0        # degrés, soit un quart de tour
SEUIL_DISTANCE = 0.8    # cm : en dessous, on considère être arrivé
SEUIL_ANGLE = 1.0       # degrés
CORRECTIONS_MAX = 6     # garde-fou contre l'acharnement sur le plancher physique


def _normaliser(angle):
    """Ramène un angle dans ]-180, 180]."""
    return (angle + 180) % 360 - 180


def _borner(valeur, limite):
    return max(-abs(limite), min(abs(limite), valeur))


async def avancer(robot, distance, pas=PAS_DISTANCE, seuil=SEUIL_DISTANCE):
    """Avance de `distance` cm (négatif = recule), en pas de `pas` au plus.

    La progression est mesurée par projection du déplacement réel sur le cap de
    départ : si le robot dérive latéralement, on ne compte que ce qui a
    réellement été gagné dans la bonne direction.
    """
    odo = robot.odometrie
    depart = (odo.x, odo.y)
    cap0 = math.radians(odo.cap)
    direction = (math.sin(cap0), math.cos(cap0))

    def progression():
        return ((odo.x - depart[0]) * direction[0]
                + (odo.y - depart[1]) * direction[1])

    # Assez d'itérations pour découper la distance en pas, plus une marge de
    # corrections résiduelles.
    budget = math.ceil(abs(distance) / pas) + CORRECTIONS_MAX
    for _ in range(budget):
        reste = distance - progression()
        if abs(reste) <= seuil:
            break
        await robot.move_distance(_borner(reste, pas))

    return progression()


async def tourner(robot, angle, pas=PAS_ANGLE, seuil=SEUIL_ANGLE, sequential=True):
    """Tourne de `angle` degrés (positif = vers la droite), par pas de `pas`.

    `sequential=False` tente la rotation d'un seul coup (utile pour le tour
    complet de reconnaissance, où la précision importe peu).
    """
    odo = robot.odometrie
    if not sequential:
        avant = odo.cap
        await robot.tourne_angle(angle)
        return angle - _normaliser(odo.cap - avant)

    # On suit la rotation CUMULÉE, pas un cap absolu : `odo.cap` est normalisé
    # dans ]-180, 180], donc comparer un cap cible non normalisé ferait sauter
    # le reste à parcourir de 360° au passage de ±180 (et le robot ferait des
    # tours complets en trop). Chaque pas valant moins de 180°, la différence
    # normalisée entre deux poses est en revanche toujours sans ambiguïté.
    cumul = 0.0
    precedent = odo.cap
    budget = math.ceil(abs(angle) / pas) + CORRECTIONS_MAX
    for _ in range(budget):
        reste = angle - cumul
        if abs(reste) <= seuil:
            break
        await robot.tourne_angle(_borner(reste, pas))
        cumul += _normaliser(odo.cap - precedent)
        precedent = odo.cap

    return angle - cumul


async def aller_a(robot, x, y, seuil=SEUIL_DISTANCE):
    """Rejoint le point (x, y) : on s'oriente, puis on avance.

    Utilisé par le mode autonome et par la stratégie de groupe pour exécuter un
    déplacement de case à case.
    """
    odo = robot.odometrie
    dx, dy = x - odo.x, y - odo.y
    distance = math.hypot(dx, dy)
    if distance <= seuil:
        return 0.0
    cap_vise = math.degrees(math.atan2(dx, dy))
    await tourner(robot, _normaliser(cap_vise - odo.cap))
    return await avancer(robot, distance)


async def aller_a_case(robot, row, column):
    """Rejoint le centre de la case (row, column)."""
    from backend.auxEpreuve import row_col_to_x_y
    x, y = row_col_to_x_y(row, column)
    return await aller_a(robot, x, y)
