// Interface de contrôle du robot.
//
// Transport : HTTP + fetch. La version d'origine utilisait un WebSocket vers
// ws://robotpi-11:8765, dont le serveur a été supprimé du dépôt : plus aucun
// bouton ne fonctionnait. On parle désormais au serveur qui sert cette page,
// quelle que soit la machine d'où on l'ouvre.

const mdp = () => document.getElementById("mdp-input").value;

let enCours = false;        // une touche de direction est-elle enfoncée ?
let directionCourante = null;

async function envoyer(route, donnees = {}) {
    try {
        const reponse = await fetch(route, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ ...donnees, mdp: mdp() }),
        });
        const resultat = await reponse.json().catch(() => ({}));
        if (!reponse.ok) {
            afficherLien(reponse.status === 403 ? "mot de passe refusé" : (resultat.erreur || `erreur ${reponse.status}`), false);
        }
        return resultat;
    } catch (e) {
        afficherLien("serveur injoignable", false);
        return null;
    }
}

function afficherLien(texte, ok) {
    const pastille = document.getElementById("lien");
    pastille.textContent = texte;
    pastille.classList.toggle("pastille-ok", ok === true);
    pastille.classList.toggle("pastille-ko", ok === false);
}

// ------------------------------------------------------------- pilotage manuel
const TOUCHES = {
    ArrowUp: "Avancer",
    ArrowDown: "Reculer",
    ArrowLeft: "Gauche",
    ArrowRight: "Droite",
};

// La carte coupe les moteurs si elle ne reçoit plus d'ordre pendant 2 s : on
// réémet donc la direction tant que la touche est maintenue.
async function maintenir(direction) {
    directionCourante = direction;
    if (enCours) return;
    enCours = true;
    while (enCours && directionCourante) {
        await envoyer("/api/move", { direction: directionCourante });
        await new Promise((r) => setTimeout(r, 300));
    }
}

function relacher() {
    enCours = false;
    directionCourante = null;
    envoyer("/api/move", { direction: "Stop" });
}

function brancherPilotage() {
    document.addEventListener("keydown", (e) => {
        const direction = TOUCHES[e.key];
        if (!direction || e.repeat) return;
        e.preventDefault();
        maintenir(direction);
    });
    document.addEventListener("keyup", (e) => {
        if (TOUCHES[e.key]) relacher();
    });

    for (const touche of document.querySelectorAll(".key")) {
        const direction = touche.dataset.direction;
        if (direction === "Stop") {
            touche.addEventListener("click", relacher);
            continue;
        }
        touche.addEventListener("pointerdown", (e) => {
            e.preventDefault();
            maintenir(direction);
        });
        touche.addEventListener("pointerup", relacher);
        touche.addEventListener("pointerleave", () => { if (enCours) relacher(); });
    }
}

// ------------------------------------------------------------------- épreuves
function brancherEpreuves() {
    for (const bouton of document.querySelectorAll(".bouton-epreuve")) {
        bouton.addEventListener("click", async () => {
            const resultat = await envoyer("/api/epreuve", { epreuve: Number(bouton.dataset.epreuve) });
            if (resultat && resultat.message) afficherLien(resultat.message, resultat.ok);
        });
    }
    document.getElementById("arret").addEventListener("click", () => envoyer("/api/stop"));
    document.getElementById("aller-case").addEventListener("click", async () => {
        const nom = document.getElementById("case-input").value.trim().toUpperCase();
        const resultat = await envoyer("/api/case", { case: nom });
        if (resultat && resultat.erreur) afficherLien(resultat.erreur, false);
    });
    document.getElementById("case-input").addEventListener("keydown", (e) => {
        if (e.key === "Enter") document.getElementById("aller-case").click();
    });
}

// ----------------------------------------------------------------------- état
function texte(id, valeur) {
    document.getElementById(id).textContent = valeur;
}

async function rafraichirEtat() {
    try {
        const reponse = await fetch("/api/etat");
        if (!reponse.ok) throw new Error(reponse.status);
        const etat = await reponse.json();

        texte("e-case", etat.case);
        texte("e-x", etat.x);
        texte("e-y", etat.y);
        texte("e-cap", `${etat.cap}°`);
        texte("e-inc", `± ${etat.incertitude} cm`);
        texte("e-simu", etat.simulation ? "simulés" : "carte I2C");
        texte("e-message", etat.message);

        const drapeaux = Object.entries(etat.drapeaux || {});
        texte("e-drapeaux", drapeaux.length
            ? drapeaux.map(([id, c]) => `#${id} en ${c}`).join(", ")
            : "aucun");
        texte("e-bloquees", (etat.cases_bloquees || []).length
            ? etat.cases_bloquees.join(", ")
            : "aucune");

        afficherLien(etat.occupe ? "occupé" : "connecté", true);
    } catch (e) {
        afficherLien("serveur injoignable", false);
    }
}

window.addEventListener("DOMContentLoaded", () => {
    brancherPilotage();
    brancherEpreuves();
    rafraichirEtat();
    setInterval(rafraichirEtat, 700);
});
