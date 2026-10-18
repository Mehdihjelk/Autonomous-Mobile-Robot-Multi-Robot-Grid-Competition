import pytest

from strategie.serveur_central import (Arbitre, LIBRE, OCCUPEE, QUARANTAINE,
                                       RESERVEE, ViolationInvariant)
from strategie.simulateur import (Horloge, RobotSimule, scenario_anneau_interblocage,
                                  scenario_blocage_physique, scenario_derive,
                                  scenario_echange_tete_a_tete, scenario_famine,
                                  scenario_panne, simulation_de_charge)


@pytest.fixture
def arbitre():
    horloge = Horloge()
    a = Arbitre(horloge=horloge, ttl=5.0)
    a.horloge_test = horloge
    return a


# ---------------------------------------------------------- base du protocole
def test_inscription_accorde_le_bail_de_depart(arbitre):
    reponse = arbitre.inscrire("r1", "C3")
    assert reponse["accord"] and reponse["case"] == "C3"
    assert arbitre.cases["C3"]["etat"] == OCCUPEE
    arbitre.verifier_invariant()


def test_deux_robots_ne_peuvent_pas_demarrer_sur_la_meme_case(arbitre):
    arbitre.inscrire("r1", "C3")
    assert not arbitre.inscrire("r2", "C3")["accord"]
    arbitre.verifier_invariant()


def test_reservation_limitee_aux_cases_adjacentes(arbitre):
    arbitre.inscrire("r1", "C3")
    assert arbitre.reserver("r1", "C4")["accord"]
    assert not arbitre.reserver("r1", "A1")["accord"]
    arbitre.verifier_invariant()


def test_transit_detient_les_deux_cases(arbitre):
    """C'est ce qui protège la frontière balayée pendant le déplacement."""
    arbitre.inscrire("r1", "C3")
    arbitre.reserver("r1", "C4")
    assert arbitre.robots["r1"].baux == {"C3", "C4"}
    arbitre.liberer("r1", "C3", arrive_en="C4")
    assert arbitre.robots["r1"].baux == {"C4"}
    assert arbitre.cases["C3"]["etat"] == LIBRE
    arbitre.verifier_invariant()


def test_on_ne_rend_pas_la_case_que_lon_occupe(arbitre):
    arbitre.inscrire("r1", "C3")
    assert not arbitre.liberer("r1", "C3")["ok"]
    arbitre.verifier_invariant()


# ----------------------------------------------------------- scénarios adverses
def test_echange_tete_a_tete():
    assert scenario_echange_tete_a_tete()


def test_anneau_interblocage():
    assert scenario_anneau_interblocage()


def test_panne_met_en_quarantaine_sans_liberer():
    assert scenario_panne()


def test_blocage_physique_corrige_la_carte():
    assert scenario_blocage_physique()


def test_derive_excessive_bloque_les_baux():
    assert scenario_derive()


def test_anti_famine():
    assert scenario_famine()


# ------------------------------------------------------------ panne et reprise
def test_bail_fantome_apres_panne(arbitre):
    """Non-régression : les baux d'un robot en panne n'étaient pas vidés, et
    ressurgissaient à la levée de la quarantaine, permettant à deux robots de
    revendiquer la même case."""
    arbitre.inscrire("mort", "C3")
    arbitre.inscrire("vivant", "C4")
    arbitre.horloge_test.avancer(6.0)
    arbitre.expirer()

    assert arbitre.robots["mort"].baux == set()
    assert arbitre.robots["mort"].baux_perdus == ["C3"]
    assert arbitre.cases["C3"]["etat"] == QUARANTAINE

    arbitre.lever_quarantaine("C3")
    arbitre.reserver("vivant", "C3")
    arbitre.verifier_invariant()      # échouait avant la correction


def test_quarantaine_nexpire_jamais_seule(arbitre):
    arbitre.inscrire("r1", "C3")
    arbitre.reserver("r1", "C4")
    arbitre.signaler_blocage("r1", "C4", "obstacle")
    arbitre.horloge_test.avancer(10_000)
    arbitre.expirer()
    assert arbitre.cases["C4"]["etat"] == QUARANTAINE
    arbitre.verifier_invariant()


def test_reinscription_apres_redemarrage(arbitre):
    arbitre.inscrire("r1", "C3")
    arbitre.horloge_test.avancer(6.0)
    arbitre.expirer()
    assert not arbitre.robots["r1"].vivant
    arbitre.lever_quarantaine("C3")
    assert arbitre.inscrire("r1", "C3")["accord"]
    assert arbitre.robots["r1"].vivant
    arbitre.verifier_invariant()


# ------------------------------------------------------------------ invariant
def test_linvariant_detecte_vraiment_une_collision(arbitre):
    """Un invariant qui ne signale jamais rien ne prouve rien : on vérifie
    qu'il attrape bien une double attribution forcée à la main."""
    arbitre.inscrire("r1", "C3")
    arbitre.inscrire("r2", "C4")
    arbitre.robots["r2"].baux.add("C3")        # collision injectée
    with pytest.raises(ViolationInvariant, match="COLLISION POSSIBLE"):
        arbitre.verifier_invariant()


def test_invariant_detecte_un_bail_fantome_en_quarantaine(arbitre):
    arbitre.inscrire("r1", "C3")
    arbitre.cases["C3"].update({"etat": QUARANTAINE, "robot": None})
    with pytest.raises(ViolationInvariant, match="fantôme"):
        arbitre.verifier_invariant()


# ------------------------------------------------------------- test de charge
@pytest.mark.parametrize("graine", [1, 20250118, 999])
def test_charge_multi_robots(graine):
    resultat = simulation_de_charge(nb_robots=6, pas=150, graine=graine, verbeux=False)
    assert resultat["deplacements"] > 50
    assert resultat["refus"] > 0, "aucune contention : le test ne prouve rien"
    assert resultat["explorees"] >= 20


def test_exploration_contourne_les_quarantaines(arbitre):
    arbitre.inscrire("r1", "F1")
    arbitre.cases["E1"].update({"etat": QUARANTAINE, "robot": None,
                                "raison": "test"})
    cible = arbitre.prochaine_cible("r1")
    assert cible != "E1"
    arbitre.verifier_invariant()
