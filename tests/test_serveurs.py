import json
import threading
import urllib.error
import urllib.request

import pytest


def _requete(url, donnees=None, methode=None):
    corps = json.dumps(donnees).encode() if donnees is not None else None
    requete = urllib.request.Request(
        url, data=corps, method=methode or ("POST" if corps else "GET"),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(requete, timeout=5) as reponse:
            brut = reponse.read().decode()
            return reponse.status, (json.loads(brut) if brut.startswith(("{", "[")) else brut)
    except urllib.error.HTTPError as e:
        brut = e.read().decode()
        return e.code, (json.loads(brut) if brut.startswith(("{", "[")) else brut)


# ------------------------------------------------------- serveur de contrôle
@pytest.fixture
def serveur_controle():
    from serveur import construire_serveur
    serveur, robot = construire_serveur(port=0, adresse="127.0.0.1", simulation=True)
    port = serveur.server_address[1]
    threading.Thread(target=serveur.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{port}", robot
    serveur.shutdown()
    serveur.server_close()


def test_sert_linterface_web(serveur_controle):
    """Non-régression : le front n'avait plus aucun backend."""
    base, _ = serveur_controle
    for fichier in ("index.html", "index.css", "index.js"):
        code, corps = _requete(f"{base}/{fichier}")
        assert code == 200 and len(corps) > 100
    code, corps = _requete(f"{base}/")
    assert code == 200 and "<!DOCTYPE html>" in corps


def test_mot_de_passe_exige(serveur_controle):
    base, _ = serveur_controle
    code, corps = _requete(f"{base}/api/move", {"direction": "Avancer", "mdp": "faux"})
    assert code == 403
    code, _ = _requete(f"{base}/api/move", {"direction": "Avancer", "mdp": "bonjour"})
    assert code == 200


def test_direction_invalide_rejetee(serveur_controle):
    base, _ = serveur_controle
    code, corps = _requete(f"{base}/api/move",
                           {"direction": "Zigzag", "mdp": "bonjour"})
    assert code == 400 and "erreur" in corps


def test_etat_expose_la_pose(serveur_controle):
    base, _ = serveur_controle
    code, etat = _requete(f"{base}/api/etat")
    assert code == 200
    for cle in ("x", "y", "cap", "case", "incertitude", "simulation"):
        assert cle in etat
    assert etat["simulation"] is True


def test_case_invalide_rejetee(serveur_controle):
    base, _ = serveur_controle
    code, corps = _requete(f"{base}/api/case", {"case": "Z9", "mdp": "bonjour"})
    assert code == 400 and "erreur" in corps


def test_pas_devasion_de_repertoire(serveur_controle):
    base, _ = serveur_controle
    code, _ = _requete(f"{base}/../serveur.py")
    assert code == 404


def test_arret_propre_exige_par_le_script_de_notation(serveur_controle):
    base, _ = serveur_controle
    code, corps = _requete(f"{base}/?param=exit", {})
    assert code == 200 and "arret" in corps


# --------------------------------------------------------- serveur de stratégie
@pytest.fixture
def serveur_central():
    from strategie.serveur_central import construire_serveur
    serveur, arbitre = construire_serveur(port=0, adresse="127.0.0.1")
    port = serveur.server_address[1]
    threading.Thread(target=serveur.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{port}", arbitre
    serveur.shutdown()
    serveur.server_close()


def test_protocole_complet_par_http(serveur_central):
    base, arbitre = serveur_central
    assert _requete(f"{base}/api/inscription", {"id": "r1", "case": "C3"})[1]["accord"]
    assert _requete(f"{base}/api/battement", {"id": "r1", "case": "C3"})[1]["connu"]
    assert _requete(f"{base}/api/reservation", {"id": "r1", "case": "C4"})[1]["accord"]
    assert _requete(f"{base}/api/liberation",
                    {"id": "r1", "case": "C3", "arrive_en": "C4"})[1]["ok"]
    code, corps = _requete(f"{base}/api/invariant")
    assert code == 200 and corps["invariant"] == "tenu"


def test_route_invariant_signale_une_rupture(serveur_central):
    base, arbitre = serveur_central
    _requete(f"{base}/api/inscription", {"id": "r1", "case": "C3"})
    _requete(f"{base}/api/inscription", {"id": "r2", "case": "C4"})
    arbitre.robots["r2"].baux.add("C3")
    code, corps = _requete(f"{base}/api/invariant")
    assert code == 500 and corps["invariant"] == "ROMPU"


def test_requete_malformee_rejetee(serveur_central):
    base, _ = serveur_central
    code, _ = _requete(f"{base}/api/reservation", {"id": "inconnu"})
    assert code == 400


def test_client_sans_serveur_ne_bouge_pas():
    """Un serveur injoignable ne doit JAMAIS valoir permission de rouler."""
    from strategie.client_strategie import ClientStrategie
    from backend.simu_terrain import CameraSimulee, Terrain
    from moteurs.simu import robot_simule

    robot, _, odo = robot_simule()
    client = ClientStrategie(robot, CameraSimulee(Terrain(), odo),
                             serveur="http://127.0.0.1:1", journal=lambda *a: None)
    assert not client.joignable()
    assert not client.inscrire()
