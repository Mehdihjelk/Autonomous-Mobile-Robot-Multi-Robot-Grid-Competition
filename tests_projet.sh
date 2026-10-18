#!/bin/sh

affiche_aide()
{
echo ""
echo "# Script de test pour proj103"
echo ""
echo "Ce script teste différentes fonctionnalités de votre programme. Il vous faudra donc exposer ces fonctionnalités afin de répondre à ce script."
echo ""
echo "Chacun des tests doit appeler votre code final, tel qu'intégré dans vos démonstrations. Vous pouvez utiliser une fonction d'entrée (main) différente."
echo "Vous pouvez avoir un unique programme de test ou bien autant que nécessaire."
echo ""
echo ""
echo "# Configuration"
echo ""
echo "Nom de commande: config"
echo ""
echo "Votre programme peut nécessiter des paquets ou bibliothèques tierces, une étape de compilation, etc ..."
echo "Le but de cette commande est de configurer tout ce dont vous avez besoin sur une carte raspberry PI sous Debian 12 pour faire tourner votre programme."
echo "On considère le réseau et le bus I2C configurés sur la carte."
echo ""
echo "Exemple"
echo "./tests_projet.sh config"
echo ""
echo "# Test du moteur"
echo ""
echo "Nom de commande: moteur"
echo ""
echo "Votre programme devra actionner vos moteurs en fonction d'une liste d'éléments, séparés par une virgule, parmis:"
echo "- rDIST: déplacement rectilinéaire du robot sur une distance de DIST centimètres. Si DIST est négatif, le robot doit reculer sans tourner."
echo "- aANG:	 rotation d'un angle de ANG degrés sur place. Si ANG est positif, le robot doit tourner vers sa droite, sinon vers sa gauche."
echo ""
echo "Exemples"
echo "./tests_projet.sh moteur r50,a45,r-50,a90,r50"
echo ""
echo ""
echo "# Test de la caméra"
echo ""
echo "Nom de commande: camera"
echo ""
echo "Votre programme devra effectuer la reconnaissance de marqueur(s) Aruco dans une image fournie en entrée."
echo "Les tailles par identifiant des marqueurs sont les mêmes que pour les épreuves d'évaluation."
echo "Votre programme devra donner ses informations sur la console ('stdout')."
echo "La sortie comportera une ligne par marqueur détécté, chaque ligne étant formatée comme 'ID x y dist angle' avec:"
echo "- ID:     identifiant du marqueur detécté"
echo "- x:      position horizontale (en pixels) du centre du marqueur dans l'image avec x=0 au centre de l'image et x croissant vers la droite de l'image"
echo "- y:      position verticale (en pixels) du centre du marqueur dans l'image avec y=0 au centre de l'image et y croissant vers le haut de l'image"
echo "- dist:   distance estimée en centimètres du marqueur par rapport à la caméra"
echo "- angle:  angle estimé en degrés entre le centre du marqueur et l'axe optique, exprimé en degré dans le sens trigonométrique"
echo ""
echo "Exemples"
echo "./tests_projet.sh camera fichier.jpg"
echo ""
echo "Exemple de sortie"
echo "6 120 -40 120 -10"
echo "0 160 20 220 20"
echo ""
echo "# Test du client/serveur web"
echo ""
echo "Nom de commande: web"
echo ""
echo "Votre programme devra lancer le serveur web sur le port indiqué et sur l'adresse localhost en mode http (et pas https)."
echo "L'application web de contrôle doit être disponible à l'adresse demandée sous le nom index.html, e.g. 'http://localhost:8080/index.html'"
echo "Votre serveur doit par ailleurs dans ce mode être capable de répondre à la requète HTTP 'POST /?param=exit', indiquant de quitter le serveur sans erreur."
echo ""
echo "Exemples"
echo "./tests_projet.sh web 8080"
echo ""
echo ""
echo "# Test des APIs du serveur de suivi"
echo ""
echo "Nom de commande: suivi"
echo ""
echo "Votre programme devra indiquer au serveur de suivi une position puis une capture de drapeau via l'API décrite sur le site."
echo "Les paramêtres sont dans l'ordre:"
echo "- SERVEUR: adresse et port du serveur de suivi (mode http utilisé, pas https)"
echo "- POS_X:   position X en centimêtre, comme indiqué dans la documentation du serveur de suivi"
echo "- POS_Y:   position Y en centimêtre, comme indiqué dans la documentation du serveur de suivi"
echo "- MID:     ID du marqueur Aruco à communiquer"
echo ""
echo "Exemples"
echo "./tests_projet.sh suivi http://localhost:8080/ 120 240 7"
echo ""
echo "Notes"
echo "* Les paramètres POS_X et POS_Y inidqueront une position dans la grilles. Ils sont donc compris dans [0,300]."
echo "* Les paramètres 'col' et 'row' utilisés par l'API de capture de drapeau devront être déduits des paramètres d'entrée POS_X et POS_Y."
echo ""
}

# Racine du projet, quel que soit le repertoire d'appel.
RACINE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
export PYTHONPATH="$RACINE:${PYTHONPATH}"

mode=$1

case "$mode" in
config)
	echo "Configuration des programmes de test"
	# Tout vient des paquets Debian : pas de pip, pas d'environnement virtuel.
	# python3-opencv fournit cv2 et le module aruco ; python3-smbus donne
	# l'acces au bus I2C de la carte moteurs.
	sudo apt-get update -qq || exit 1
	sudo apt-get install -y python3 python3-numpy python3-requests \
	                        python3-opencv python3-smbus || exit 1
	# Verification : chaque import doit passer.
	python3 - <<'EOF' || exit 1
import sys
manquants = []
for module in ("numpy", "requests", "cv2", "smbus"):
    try:
        __import__(module)
    except ImportError:
        manquants.append(module)
if manquants:
    print("modules manquants :", ", ".join(manquants), file=sys.stderr)
    sys.exit(1)
print("dependances completes")
EOF
	exit 0
	;;
moteur)
	if [ "$#" -ne 2 ]; then
		echo "Erreur, pas de paramètres moteurs"
		exit 1
	fi
	param_moteurs=$2
	echo "Test des moteurs avec la séquence $param_moteurs"
	exec python3 "$RACINE/outils_test.py" moteur "$param_moteurs"
	;;

camera)
	if [ "$#" -ne 2 ]; then
		echo "Erreur, pas de paramètres caméra"
		exit 1
	fi

	param_camera=$2
	echo "Test de la caméra avec l'image $param_camera" >&2
	# La sortie standard ne doit contenir que les lignes « ID x y dist angle ».
	exec python3 "$RACINE/outils_test.py" camera "$param_camera"
	;;


web)
	if [ "$#" -ne 2 ]; then
		echo "Erreur, pas de paramètres client web"
		exit 1
	fi
	port_web=$2
	echo "Test du client/serveur web sur le port $port_web"
	# Sert website/index.html et repond a POST /?param=exit pour s'arreter.
	exec python3 "$RACINE/serveur.py" --port "$port_web" --adresse localhost
	;;


suivi)

	if [ "$#" -ne 5 ]; then
		echo "Erreur, pas de paramètres de serveur de suivi"
		exit 1
	fi
	serveur=$2
	pos_x=$3
	pos_y=$4
	mark_id=$5
	echo "Test du serveur de suivi $serveur: envoi position $pos_x $pos_y puis envoi marqueur $mark_id"
	exec python3 "$RACINE/outils_test.py" suivi "$serveur" "$pos_x" "$pos_y" "$mark_id"
	;;

aide | -h)
	affiche_aide
	exit 0
	;;

*) echo "Mauvais paramètre, regardez l'aide avec -h ou aide"
	exit 1
	;;
esac


