# Protocole d'arbitrage par baux de cases

Stratégie de coordination multi-robots pour l'épreuve de groupe de PROJ103.

---

## 1. Pourquoi l'exclusion mutuelle

L'approche intuitive pour coordonner plusieurs robots consiste à **planifier des
trajectoires qui ne se croisent pas** : modéliser les situations possibles par un
graphe d'états, calculer les plus courts chemins (Floyd-Warshall par exemple),
puis répartir les robots par backtracking vers les zones non visitées.

Elle a été écartée. Dans ce contexte précis, elle est **structurellement
incapable** de garantir l'absence de collision, pour trois raisons.

### 1. Le planificateur raisonnerait sur des données fausses

Son modèle du monde ne peut venir que de l'odométrie remontée par chaque robot.
Elle dérive, et rien ne la borne naturellement. Un planificateur qui raisonne sur
des positions erronées produit des trajectoires sans croisement *dans son
modèle*, et des collisions sur le terrain.

### 2. Un robot en panne deviendrait un obstacle invisible

La réaction naturelle face à un robot qui ne répond plus est de le **retirer du
modèle** et de redistribuer son travail. Sauf qu'il reste **physiquement posé sur
la grille**. Plus un robot tombe en panne, plus le planificateur devient
confiant, et plus il a tort. Un évitement *a priori* ne peut pas éviter un
obstacle dont il ignore l'existence.

### 3. Rien ne permettrait au terrain de contredire la carte

Les robots n'ont qu'un seul capteur, la caméra, et les autres robots ne portent
pas de marqueur : ils sont littéralement invisibles les uns pour les autres. Sans
boucle de rétroaction physique, une erreur du modèle ne se corrige jamais.

### Et le problème est difficile en soi

*Optimiser le parcours de k robots sur un graphe vers certains sommets sans
qu'ils s'intersectent* est un problème dur. En faire dépendre la sûreté, c'est
faire dépendre la sûreté d'un algorithme qu'on n'a ni le temps ni les moyens de
prouver.

---

## 2. Le principe : interdire au lieu de planifier

> **On ne planifie plus pour éviter. On rend l'entrée impossible sans permission.**

La grille est une ressource partagée, protégée par exclusion mutuelle. Chaque
case est un verrou, détenu par au plus un robot à la fois.

### Invariant de sûreté

> À tout instant, **chaque case est louée à au plus un robot**, et **l'emprise
> physique d'un robot ne recouvre que des cases dont il détient le bail**.

La seconde moitié est tenable grâce à une propriété géométrique du robot : le
châssis mesure 29 cm de côté, soit 41 cm de diagonale, pour une case de 50 cm. Un
robot centré sur sa case y reste donc entièrement, **même en tournant sur
lui-même de 360°** — le geste de capture est ainsi sûr sans précaution
particulière.

### Transit : détenir les deux cases

Pour aller de A vers B, le robot balaie la frontière entre A et B. Il doit donc
détenir **A et B simultanément** pendant tout le trajet, et ne rend A qu'après
avoir confirmé son arrivée en B.

```
   état sûr          transit (2 baux)        état sûr
  ┌─────┬─────┐     ┌─────┬─────┐         ┌─────┬─────┐
  │ R ▓ │     │ --> │ R ▓▓▓▓▓ ▓ │   -->   │     │ ▓ R │
  │  A  │  B  │     │  A  │  B  │         │  A  │  B  │
  └─────┴─────┘     └─────┴─────┘         └─────┴─────┘
   bail: {A}         bail: {A, B}          bail: {B}
```

---

## 3. Ce que la stratégie garantit, et pourquoi

| Propriété | Mécanisme | Pourquoi ça tient |
|---|---|---|
| **Absence de collision** | baux exclusifs | Ne découle plus de la qualité du plan mais de l'exclusivité des attributions. Le planificateur peut être glouton, myope et se tromper : le système reste sûr. |
| **Pas d'échange tête-à-tête** | détenir sa source pendant le transit | R1 en A veut B, R2 en B veut A : chacun détient sa propre case, donc aucun n'obtient celle de l'autre. C'est le cas que la seule réservation de destination laisse passer. |
| **Pas d'interblocage** | refus non bloquant | Un refus ne met jamais un robot en attente : il garde sa case, état sûr à un seul bail, et retentera éventuellement ailleurs. Aucun cycle d'attente ne peut se former. |
| **Pas de famine** | vieillissement des priorités | Chaque refus incrémente la priorité du demandeur ; une case libérée va au prétendant le plus ancien. L'attente est bornée. |
| **Panne sûre** | quarantaine, pas libération | Un bail dont les battements cessent passe en `QUARANTAINE`. **C'est le point clé de la panne sûre.** |
| **Rétroaction physique** | signalement de blocage | Un robot bloqué déclare la case visée, qui passe en quarantaine. **C'est la seule rétroaction physique disponible.** |
| **Dérive bornée** | budget d'incertitude | Au-delà d'une demi-case d'incertitude, plus aucun bail n'est accordé : le robot doit d'abord se recaler sur un repère fixe. **Corrige la faille 1**, et c'est ce qui maintient vraie la seconde moitié de l'invariant. |

### Le point d'architecture le plus important

La sûreté **ne dépend plus du planificateur**. Celui de `prochaine_cible()` est
volontairement trivial : un parcours en largeur vers la case inexplorée la plus
proche. On peut le remplacer par n'importe quoi — y compris par le Floyd-Warshall
sur graphe d'états — sans jamais risquer une collision. Correction et performance
sont devenues deux problèmes séparés.

---

## 4. États d'une case

```
                   reserver()                liberer(arrive_en=)
      LIBRE ─────────────────────> RESERVEE ────────────────────> OCCUPEE
        ^                              │                             │
        │                              │ signaler_blocage()          │ liberer()
        │ lever_quarantaine()          v                             v
        └──────────────────────── QUARANTAINE <──────────────── (battements perdus)
                (geste volontaire       ^                             
                 de l'opérateur)        │ une quarantaine n'expire JAMAIS seule
```

Une quarantaine ne se lève que sur intervention explicite : rien ne permet au
serveur de savoir qu'un obstacle qu'il n'a jamais vu a été retiré.

---

## 5. Messages

Tout en HTTP + JSON. Chaque requête porte `{"id": "<robot>"}`.

| Route | Corps | Réponse | Rôle |
|---|---|---|---|
| `POST /api/inscription` | `case` | `accord`, `case`, `ttl` | Entrer en jeu, obtenir le bail de sa case de départ. |
| `POST /api/battement` | `case`, `incertitude` | `baux`, `cible`, `doit_se_recaler`, `quarantaines`, `drapeaux` | Battement de cœur. **Seule chose qui maintient un bail en vie.** |
| `POST /api/reservation` | `case` | `accord`, `motif` | Demander le bail d'une case **adjacente**. Non bloquant. |
| `POST /api/liberation` | `case`, `arrive_en` | `ok`, `baux` | Rendre la case source après arrivée confirmée. |
| `POST /api/blocage` | `case`, `detail` | `ok`, `quarantaine` | « Je suis physiquement bloqué en allant là. » |
| `POST /api/drapeau` | `drapeau`, `case` | `drapeaux` | Signaler un drapeau localisé. |
| `POST /api/cible` | — | `case` | Demander la prochaine case à viser. |
| `POST /api/quarantaine/lever` | `case` | `ok` | Opérateur : l'obstacle est retiré. |
| `GET /api/carte` | — | état global | Supervision. |
| `GET /api/invariant` | — | `tenu` / `ROMPU` | Vérification en direct. HTTP 500 si rompu. |

### Cycle d'un robot

```
  battement ──> doit_se_recaler ? ──oui──> chercher un repère fixe, recaler
      │                │non
      │                v
      │          relever les drapeaux ──> signaler
      │                │
      │                v
      │          demander une cible ──> reservation
      │                                      │
      │                      refus <─────────┴─────────> accord
      │                        │                            │
      │                   rester en place              aller_a_case()
      │                   (état sûr)                        │
      │                        │                 bloqué ────┴──── arrivé
      │                        │                    │              │
      │                        │              signaler_blocage  liberation
      └────────────────────────┴────────────────────┴──────────────┘
```

**Règle de sûreté du client** : un serveur injoignable ne vaut **jamais**
permission. Le robot s'arrête. Le défaut par défaut est le refus, jamais
l'autorisation tacite : un robot qui continue sur sa dernière instruction pendant
que l'arbitre est muet roule sans arbitrage.

---

## 6. Vérification

`strategie/simulateur.py` rejoue six scénarios adverses et un test de charge, en
vérifiant l'invariant **après chaque opération d'arbitrage**.

```
python3 -m strategie.simulateur
```

| Scénario | Ce qui est vérifié |
|---|---|
| Échange tête-à-tête | Deux demandes croisées : les deux refusées. |
| Anneau 2×2 | Quatre robots en cycle : 4/4 refusés, chacun garde sa case. |
| Panne d'un robot | La case passe en `QUARANTAINE`, pas `LIBRE`. Le voisin est refusé. |
| Blocage physique | La case visée passe en quarantaine ; un second robot est protégé. |
| Dérive d'odométrie | Bail accordé à ±10 cm, refusé à ±40 cm, re-accordé après recalage. |
| Famine | Après N refus, le patient obtient la case avant un nouvel arrivant. |
| Charge (6 robots) | ~8 000 vérifications d'invariant, avec pannes et obstacles. |

Le test de charge **échoue volontairement si aucun refus n'a lieu** : sans
contention, il ne prouverait rien.

---

## 7. Limites assumées

- **Les repères fixes doivent être relevés.** `backend/vision.REPERES_FIXES` est
  vide par défaut. Sans lui, le recalage est impossible et un robot trop dérivé
  reste bloqué au lieu de rouler à l'aveugle — comportement sûr, mais à l'arrêt.
  C'est la seule donnée de terrain qui manque pour que la chaîne soit complète.
- **Granularité à la case.** Deux robots ne peuvent pas se croiser dans un
  couloir d'une case de large. C'est le prix de la garantie ; sur une grille 6×6
  à quelques robots, le test de charge montre que le débit reste largement
  suffisant.
- **Le serveur central est un point unique de défaillance.** C'était déjà le cas
  avant. La différence est qu'ici sa panne **immobilise** les robots au lieu de
  les laisser rouler sans arbitrage.
- **La géométrie est supposée.** Le châssis de 29 cm vient de `plan_robot.svg`.
  Un robot plus large que 50 cm en diagonale invaliderait la seconde moitié de
  l'invariant, et il faudrait alors louer aussi les cases voisines.
