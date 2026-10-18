#!/usr/bin/env python3

import random

from backend.auxEpreuve import case_vers_nom, cases_voisines, nom_vers_case
from strategie.serveur_central import (Arbitre, ViolationInvariant,
                                       LIBRE, RESERVEE, OCCUPEE, QUARANTAINE)


class Horloge:
    """Horloge virtuelle : simulation déterministe et instantanée."""

    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def avancer(self, duree):
        self.t += duree


class RobotSimule:
    """Robot obéissant au protocole de baux.

    Reproduit fidèlement le cycle du vrai client : battement, demande de cible,
    réservation, transit, confirmation d'arrivée, libération de la source.
    """

    DERIVE_PAR_CASE = 1.5      # cm d'incertitude gagnés par déplacement

    def __init__(self, arbitre, identifiant, case, verifier=None, alea=None):
        self.arbitre = arbitre
        self.alea = alea or random.Random(hash(identifiant) & 0xFFFF)
        self.id = identifiant
        self.case = case
        self.incertitude = 2.0
        self.en_panne = False
        self.immobile = False       # ne fait que battre, n'explore pas
        self.bloque_vers = None     # case où il rencontrera un obstacle
        self.deplacements = 0
        self.refus = 0
        self.recalages = 0
        self.verifier = verifier or (lambda: None)

        self._appeler(self.arbitre.inscrire, identifiant, case)

    def _appeler(self, fonction, *args, **kwargs):
        """Appelle l'arbitre puis vérifie immédiatement l'invariant."""
        resultat = fonction(*args, **kwargs)
        self.verifier()
        return resultat

    def pas(self):
        """Un cycle complet. Renvoie True si le robot a progressé."""
        if self.en_panne:
            return False

        etat = self._appeler(self.arbitre.battement, self.id,
                             self.case, self.incertitude)
        if not etat.get("connu"):
            return False

        # Dérive trop forte : le serveur refuse les baux jusqu'au recalage.
        if etat.get("doit_se_recaler"):
            self.incertitude = 3.0          # recalage sur un repère fixe
            self.recalages += 1
            return True

        if self.immobile:
            return True

        cible = self._appeler(self.arbitre.prochaine_cible, self.id)
        if cible is None:
            # Plus rien d'inexploré d'atteignable : on patrouille au hasard.
            # C'est ce qui maintient la contention entre robots, et donc ce qui
            # met réellement l'arbitrage à l'épreuve.
            voisines = [case_vers_nom(r, c)
                        for r, c in cases_voisines(*nom_vers_case(self.case))]
            if not voisines:
                return False
            cible = self.alea.choice(voisines)

        reponse = self._appeler(self.arbitre.reserver, self.id, cible)
        if not reponse.get("accord"):
            self.refus += 1
            return False        # on reste dans sa case : état sûr

        # --- transit : le robot détient maintenant source ET destination -----
        if self.bloque_vers == cible:
            self._appeler(self.arbitre.signaler_blocage, self.id, cible,
                          "roues immobiles")
            self.bloque_vers = None
            return True

        source = self.case
        self._appeler(self.arbitre.liberer, self.id, source, cible)
        self.case = cible
        self.incertitude += self.DERIVE_PAR_CASE
        self.deplacements += 1
        return True


def _invariant(arbitre):
    def verifier():
        arbitre.verifier_invariant()
    return verifier


# ===========================================================================
#                           SCÉNARIOS ADVERSES
# ===========================================================================
def scenario_echange_tete_a_tete():
    """Deux robots adjacents veulent chacun la case de l'autre.

    C'est le cas que la simple réservation de destination laisse passer : les
    deux robots se croiseraient sur la frontière. Détenir sa case d'origine
    pendant le transit l'interdit.
    """
    horloge = Horloge()
    arbitre = Arbitre(horloge=horloge)
    verifier = _invariant(arbitre)

    r1 = RobotSimule(arbitre, "r1", "C3", verifier)
    r2 = RobotSimule(arbitre, "r2", "C4", verifier)

    a = arbitre.reserver("r1", "C4")    # r1 veut la case de r2
    verifier()
    b = arbitre.reserver("r2", "C3")    # r2 veut la case de r1
    verifier()

    assert not a["accord"], "r1 n'aurait pas dû obtenir C4"
    assert not b["accord"], "r2 n'aurait pas dû obtenir C3"
    print("  échange tête-à-tête  : les deux demandes refusées, "
          f"aucun croisement possible")
    print(f"      r1 -> C4 : {a['motif']}")
    print(f"      r2 -> C3 : {b['motif']}")
    return True


def scenario_anneau_interblocage():
    """Quatre robots en cycle sur un carré 2x2, chacun voulant la case du suivant.

    Configuration canonique d'interblocage. Comme un refus ne met jamais un
    robot en attente bloquante, aucun cycle d'attente ne se forme : les quatre
    sont refusés et restent dans un état sûr.
    """
    horloge = Horloge()
    arbitre = Arbitre(horloge=horloge)
    verifier = _invariant(arbitre)

    anneau = ["C3", "C4", "D4", "D3"]
    for i, case in enumerate(anneau):
        RobotSimule(arbitre, f"r{i}", case, verifier)

    refuses = 0
    for i, case in enumerate(anneau):
        suivante = anneau[(i + 1) % 4]
        reponse = arbitre.reserver(f"r{i}", suivante)
        verifier()
        if not reponse["accord"]:
            refuses += 1

    assert refuses == 4, f"{4 - refuses} robot(s) ont obtenu un bail du cycle"
    # Chacun détient toujours exactement sa propre case : état sûr.
    for i, case in enumerate(anneau):
        assert arbitre.robots[f"r{i}"].baux == {case}
    print(f"  anneau 2x2           : 4/4 demandes refusées, chaque robot garde "
          f"sa case (aucun interblocage)")
    return True


def scenario_panne():
    """Un robot cesse de battre. Sa case doit passer en QUARANTAINE, pas LIBRE.

    C'est la correction de la contradiction centrale de la stratégie d'origine,
    qui retirait un robot en panne du modèle alors qu'il restait sur la grille.
    """
    horloge = Horloge()
    arbitre = Arbitre(horloge=horloge, ttl=5.0)
    verifier = _invariant(arbitre)

    mort = RobotSimule(arbitre, "mort", "C3", verifier)
    vivant = RobotSimule(arbitre, "vivant", "C4", verifier)
    vivant.immobile = True          # il reste en C4 et se contente de battre

    mort.en_panne = True
    # Le temps passe : le robot vivant continue de battre, le mort se tait.
    for _ in range(6):
        horloge.avancer(1.0)
        vivant.pas()
        arbitre.expirer()
        verifier()
    perdus = [r.id for r in arbitre.robots.values() if not r.vivant]

    etat = arbitre.cases["C3"]["etat"]
    assert perdus == ["mort"], f"robots présumés en panne : {perdus}"
    assert etat == QUARANTAINE, f"C3 est {etat}, attendu QUARANTAINE"

    # le robot vivant, resté en C4, ne peut pas entrer dans la case du mort
    assert arbitre.robots["vivant"].case == "C4"
    reponse = arbitre.reserver("vivant", "C3")
    verifier()
    assert not reponse["accord"]
    print(f"  panne d'un robot     : C3 -> {etat} (pas LIBRE)")
    print(f"      le voisin est refusé : {reponse['motif']}")

    # ... jusqu'à ce qu'un opérateur constate que l'épave est retirée
    arbitre.lever_quarantaine("C3")
    verifier()
    reponse = arbitre.reserver("vivant", "C3")
    verifier()
    assert reponse["accord"]
    print(f"  après lever_quarantaine : accès rétabli ({reponse['case']})")
    return True


def scenario_blocage_physique():
    """Un robot se bloque : le monde physique doit corriger le modèle."""
    horloge = Horloge()
    arbitre = Arbitre(horloge=horloge)
    verifier = _invariant(arbitre)

    robot = RobotSimule(arbitre, "r1", "C3", verifier)
    robot.bloque_vers = "C4"             # obstacle invisible en C4

    arbitre.reserver("r1", "C4")
    verifier()
    arbitre.signaler_blocage("r1", "C4", "roues immobiles 0.4s")
    verifier()

    etat = arbitre.cases["C4"]
    assert etat["etat"] == QUARANTAINE
    assert "C4" not in arbitre.robots["r1"].baux
    assert arbitre.robots["r1"].case == "C3"
    print(f"  blocage physique     : C4 -> QUARANTAINE ({etat['raison']})")
    print(f"      le robot est resté en C3, bail rendu")

    # un autre robot ne s'y fera pas piéger à son tour
    RobotSimule(arbitre, "r2", "C5", verifier)
    reponse = arbitre.reserver("r2", "C4")
    verifier()
    assert not reponse["accord"]
    print(f"      un second robot est protégé : {reponse['motif']}")
    return True


def scenario_derive():
    """Un robot trop incertain de sa position ne doit plus obtenir de bail.

    Sans cela, la seconde moitié de l'invariant (« l'emprise du robot ne
    recouvre que ses baux ») devient fausse et toute la garantie s'effondre.
    """
    horloge = Horloge()
    arbitre = Arbitre(horloge=horloge, seuil_incertitude=25.0)
    verifier = _invariant(arbitre)

    RobotSimule(arbitre, "r1", "C3", verifier)

    arbitre.battement("r1", "C3", incertitude=10.0)
    verifier()
    bon = arbitre.reserver("r1", "C4")
    verifier()
    assert bon["accord"]

    arbitre.liberer("r1", "C3", arrive_en="C4")
    verifier()
    arbitre.battement("r1", "C4", incertitude=40.0)      # dérive trop forte
    verifier()
    refus = arbitre.reserver("r1", "C5")
    verifier()
    assert not refus["accord"]
    print(f"  dérive excessive     : à ±10 cm le bail est accordé, "
          f"à ±40 cm il est refusé")
    print(f"      {refus['motif']}")

    arbitre.battement("r1", "C4", incertitude=3.0)       # après recalage
    verifier()
    apres = arbitre.reserver("r1", "C5")
    verifier()
    assert apres["accord"]
    print(f"      après recalage (±3 cm) : bail de nouveau accordé")
    return True


def scenario_famine():
    """Un robot refusé plusieurs fois doit finir par obtenir la case disputée."""
    horloge = Horloge()
    arbitre = Arbitre(horloge=horloge)
    verifier = _invariant(arbitre)

    RobotSimule(arbitre, "occupant", "C4", verifier)
    RobotSimule(arbitre, "patient", "C3", verifier)
    RobotSimule(arbitre, "presse", "C5", verifier)

    for _ in range(5):                  # le patient accumule de la priorité
        arbitre.reserver("patient", "C4")
        verifier()
    priorite = arbitre.robots["patient"].priorite

    arbitre.liberer("occupant", "C4", arrive_en=None)   # refusé : case occupée
    arbitre.reserver("occupant", "D4")
    arbitre.liberer("occupant", "C4", arrive_en="D4")   # l'occupant s'en va
    verifier()

    vole = arbitre.reserver("presse", "C4")      # le pressé tente de passer devant
    verifier()
    assert not vole["accord"], "le pressé n'aurait pas dû passer devant"
    obtenu = arbitre.reserver("patient", "C4")
    verifier()
    assert obtenu["accord"]
    print(f"  anti-famine          : après {priorite} refus, le patient obtient C4")
    print(f"      le pressé est écarté : {vole['motif']}")
    return True


# ===========================================================================
#                              TEST DE CHARGE
# ===========================================================================
def simulation_de_charge(nb_robots=6, pas=400, graine=20250118, verbeux=True):
    """N robots explorent la grille en concurrence, avec pannes et blocages.

    L'invariant est vérifié après chacune des milliers d'opérations.
    """
    alea = random.Random(graine)
    horloge = Horloge()
    arbitre = Arbitre(horloge=horloge, ttl=8.0)
    verifier = _invariant(arbitre)

    # Départs répartis sur le bord bas de la grille
    departs = ["F1", "F2", "F3", "F4", "F5", "F6"][:nb_robots]
    robots = [RobotSimule(arbitre, f"r{i+1}", case, verifier,
                          alea=random.Random(graine + i))
              for i, case in enumerate(departs)]

    # Deux obstacles invisibles, et une panne programmée
    robots[0].bloque_vers = "D1"
    if nb_robots > 2:
        robots[2].bloque_vers = "C3"
    panne_a = pas // 3

    operations = 0
    verifications = [0]
    invariant_brut = arbitre.verifier_invariant

    def compter():
        verifications[0] += 1
        return invariant_brut()
    arbitre.verifier_invariant = compter

    for tour in range(pas):
        horloge.avancer(1.0)
        if tour == panne_a and nb_robots > 1:
            robots[1].en_panne = True
            if verbeux:
                print(f"    [tour {tour}] {robots[1].id} tombe en panne en "
                      f"{robots[1].case}")
        for robot in robots:
            robot.pas()
            operations += 1
        arbitre.expirer()
        verifier()

    explorees = len(arbitre.explorees)
    quarantaines = arbitre.quarantaines()
    deplacements = sum(r.deplacements for r in robots)
    refus = sum(r.refus for r in robots)
    recalages = sum(r.recalages for r in robots)

    if verbeux:
        print(f"\n    robots            : {nb_robots}")
        print(f"    tours             : {pas}   opérations d'arbitrage : ~{operations}")
        print(f"    déplacements      : {deplacements}")
        print(f"    refus (sains)     : {refus}")
        print(f"    recalages imposés : {recalages}")
        print(f"    cases explorées   : {explorees}/36")
        print(f"    vérifications de l'invariant : {verifications[0]}")
        print(f"    quarantaines      : {len(quarantaines)} -> "
              f"{ {k: v[:45] for k, v in quarantaines.items()} }")
        print(f"    INVARIANT         : tenu sur la totalité des opérations")

    arbitre.verifier_invariant = invariant_brut
    assert deplacements > 0, "aucun robot n'a bougé : la stratégie est bloquée"
    assert explorees > nb_robots, "aucune exploration : pas de progrès"
    assert refus > 0, ("aucun refus en {} tours : les robots ne se gênent "
                       "jamais, le test ne prouve rien".format(pas))
    return {"explorees": explorees, "deplacements": deplacements,
            "refus": refus, "recalages": recalages,
            "verifications": verifications[0], "quarantaines": quarantaines}


def main():
    print("=" * 74)
    print("STRATÉGIE DE GROUPE — vérification par scénarios adverses")
    print("=" * 74)
    scenarios = [
        ("Échange tête-à-tête", scenario_echange_tete_a_tete),
        ("Anneau d'interblocage", scenario_anneau_interblocage),
        ("Panne d'un robot", scenario_panne),
        ("Blocage physique", scenario_blocage_physique),
        ("Dérive d'odométrie", scenario_derive),
        ("Famine", scenario_famine),
    ]
    for nom, fonction in scenarios:
        print(f"\n[{nom}]")
        fonction()

    print("\n" + "=" * 74)
    print("TEST DE CHARGE — 6 robots, pannes et obstacles invisibles")
    print("=" * 74)
    simulation_de_charge()

    print("\n" + "=" * 74)
    print("Tous les scénarios passent : l'invariant de sûreté n'est jamais rompu.")
    print("=" * 74)


if __name__ == "__main__":
    main()
