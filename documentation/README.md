<!-- 




                                    NE PAS LIRE ICI, LIRE SUR LE GIT LAB




-->


# Liens, documents et informations utiles

## Communication avec la Raspberry

- Se connecter à la Raspberry:
    - __Etape 1__ : Se connecter sur son ordinateur au WIFI **Campus-Telecom**
    - __Etape 2__ : Aller sur son terminal et taper la commande ```ssh lemeilleur@robotpi-11```,
    - __Etape 3__ : Le mot de passe est ```0123456789``` (certes pas hyper sécurisé)

- Transférer un ficher/dossier sur la Raspberry:
    - __Etape 1__ : Se connecter sur son ordinateur au WIFI **Campus-Telecom**
    - __Etape 2__ : Aller sur son terminal, **vérifier que votre terminal est bien situé à la racine de votre projet**. Si ce n'est pas le cas, entrez dans le terminal <br />```cd leCheminVersLaRacineDuProjet```
    - __Etape 3__ : Une que votre terminal est au bon endroit, tapez <br />
Si c'est un fichier : ```scp leCheminVersLeFichier lemeilleur@robotpi-11:leDossierDansLequelTransférer```. <br />
Si c'est un dossier : ```scp -r leCheminVersLeDossier lemeilleur@robotpi-11:leDossierDansLequelTransférer```. <br />
    De base, les fichier qu'on transfert sont dans ```lemeilleur@robotpi-11:```
    - __Etape 4__ : Le mot de passe est ```0123456789``` (certes pas hyper sécurisé)


## Manipulation des fichiers depuis la Raspberry

- __Installer_ un package:  
    - Si c'est_ un __package python__:
```bash
sudo apt install python3-monpackage 
```

    - Sinon:
```bash
sudo apt install monpackage 
```

- __Copier__ des fichiers:
```bash
sudo cp -r cheminVersDossierOuFichierACopier cheminDestination 
```

- __Supprimer__ des fichiers:
```bash
sudo rm -r cheminVersDossierOuFichierASuppr
```


-__Permissions__ site html : 
Après avoir ajouté le dossier website sur la carte pour écraser l'ancien :
```bash
sudo cp index.html /var/www/html/
```