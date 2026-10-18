# Robot capture-de-drapeaux — team1 (PROJ103)

Robot roulant autonome qui explore une grille 6×6 de cases de 50 cm, y repère
des drapeaux matérialisés par des marqueurs ArUco, et les déclare au serveur de
suivi de l'école. Plusieurs robots jouent simultanément, coordonnés par un
serveur central.

Matériel : Raspberry Pi, carte de contrôle moteurs sur bus I²C, deux moteurs à
encodeurs (3840 ticks/tour, roues de 6,5 cm, entraxe 18,5 cm), une caméra USB
calibrée, châssis découpé au FabLab (`plan_robot.svg`).

---

## Démarrage rapide

Tout fonctionne **sans matériel** : si le bus I²C ou la caméra sont absents, la
pile bascule sur des simulateurs. C'est ce qui rend le projet testable ailleurs
que sur la carte.

```bash
# dépendances (Raspberry sous Debian 12)
./tests_projet.sh config

# la suite de tests complète
python3 -m pytest tests/ -q

# le robot, en autonome et sans matériel
python3 client_new.py --simulation --autonome

# l'interface web de contrôle
python3 serveur.py --port 8080 --simulation
# puis http://localhost:8080/index.html

# le serveur central de stratégie, et sa vérification
python3 -m strategie.serveur_central --port 8080
python3 -m strategie.simulateur
```

---

## Architecture

```
client_new.py ───── point d'entrée : mode coordonné, repli en autonome
  │
  ├── strategie/ ── stratégie de GROUPE (arbitrage par baux de cases)
  │     serveur_central.py   l'arbitre : baux, quarantaines, invariant
  │     client_strategie.py  côté robot du protocole
  │     simulateur.py        scénarios adverses + test de charge
  │     protocole.md         la spécification et ses garanties
  │
  ├── backend/ ──── comportement d'UN robot
  │     autonome.py          balayage de la grille (mode solitaire)
  │     deplacement.py       avancer / tourner, en boucle fermée
  │     suiviDeplacement.py  odométrie + API du serveur de suivi
  │     auxEpreuve.py        conversions cases ⇄ centimètres
  │     vision.py            détection ArUco, distance, angle
  │     simu_terrain.py      terrain et caméra simulés
  │
  ├── moteurs/ ──── asservissement
  │     controleMoteurs.py   boucle P, décélération, détection de blocage
  │     controller.py        pilote I²C (fourni par l'école, Apache 2.0)
  │     simu.py              carte moteurs simulée
  │
  ├── serveur.py ── interface web de contrôle manuel (HTTP, stdlib seule)
  ├── website/ ──── la page de contrôle
  ├── outils_test.py ─ points d'entrée de tests_projet.sh
  └── tests/ ────── 114 tests
```

### Repère de coordonnées

Une seule convention dans tout le projet :

```
    y (cm)
    ^
300 +-----+-----+-----+-----+-----+-----+
    |  A1 |  A2 |  A3 |  A4 |  A5 |  A6 |   rang A, le plus éloigné
250 +-----+-----+-----+-----+-----+-----+
    | ... |     |     |     |     |     |
 50 +-----+-----+-----+-----+-----+-----+
    |  F1 |  F2 |  F3 |  F4 |  F5 |  F6 |   rang F, le plus proche
  0 +-----+-----+-----+-----+-----+-----+--> x (cm)
    0    50   100   150   200   250   300
```

Cap du robot : **0° = +y**, **+90° = +x**. Un angle positif fait donc tourner le
robot **vers sa droite**, comme l'exige `tests_projet.sh`. Le robot démarre hors
grille, en (25, −25), face au nord.

---

## Les deux modes

**Coordonné** — le robot est client du serveur central et obéit au protocole de
baux : il ne se déplace que sur permission explicite. C'est le mode de l'épreuve
de groupe, décrit dans [`strategie/protocole.md`](strategie/protocole.md).

**Autonome** — si aucun serveur central ne répond, le robot balaie seul la
grille en serpentin, scanne chaque case sur 360° (le champ de vision ne fait que
20°), rejoint chaque drapeau aperçu et le déclare. Aucune coordination, mais le
robot reste utile.

La bascule est automatique.

---

## Sécurité du mouvement

Le robot n'a aucun capteur d'obstacle : la caméra ne voit que les marqueurs, et
les autres robots n'en portent pas. La seule détection possible est le blocage
des roues :

- **Détection de blocage** — si les encodeurs n'avancent plus alors que les
  moteurs sont commandés, `RobotBloque` est levée et les moteurs sont arrêtés.
  Sans cela, le robot poussait indéfiniment : la sécurité firmware
  (`set_motor_shutdown_timeout`) ne se déclenche jamais, puisque la boucle
  d'asservissement envoie un ordre toutes les 10 ms.
- **Durée bornée** par mouvement (`MouvementTropLong`).
- **Remontée au serveur central**, qui met la case visée en quarantaine : le
  monde physique corrige la carte.

---

## Calibration

Deux constantes, dans `moteurs/controleMoteurs.py`, chacune utilisée **dans les
deux sens** (commande et mesure) :

| Constante | Rôle | Si le robot… |
|---|---|---|
| `GAIN_DISTANCE` | rapport distance réelle / distance géométrique | va trop loin → diminuer |
| `ENTRAXE_EFFECTIF` | entraxe corrigé pour les rotations | tourne trop → augmenter |
| `correction` (instance) | déséquilibre gauche/droite | tire à droite → augmenter |
| `inversion_droite` | moteur droit monté en miroir | avance au lieu de tourner → passer à −1 |

```bash
python3 mesure_actions.py --angle 45 --repetitions 8      # mesurer l'erreur cumulée
python3 markeurs_Aruco/calibrate_camera.py 'photos/*.jpg' # recalibrer la caméra
```

---

## À renseigner avant l'épreuve

`backend/vision.REPERES_FIXES` est **vide**. Ce dictionnaire associe chaque
marqueur fixe du terrain (ID 1 à 4) à sa position en centimètres :

```python
REPERES_FIXES = {1: (150.0, 300.0), 2: (0.0, 150.0), ...}
```

Sans lui, le robot ne peut pas annuler sa dérive d'odométrie. Il se comporte
alors de façon sûre — il s'arrête plutôt que de rouler à l'aveugle — mais il
s'arrête. C'est la seule mesure de terrain qui manque pour que la chaîne soit
complète.
