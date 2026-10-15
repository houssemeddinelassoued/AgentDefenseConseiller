"""Éléments partagés par les pages de l'application Streamlit."""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import pandas as pd
import streamlit as st

from agent_besoins.config import Config
from agent_besoins.modeles import Resultat, Trace
from agent_besoins.moteurs import (ClientOllama, MoteurIndisponible, est_adresse_locale, libelle_moteur,
                                   masquer_identifiants, normaliser_modele)
from agent_besoins.pipeline import titres_references
from agent_besoins.rapport import construire_html

# Streamlit Community Cloud monte le dépôt sous /mount/src : « localhost » y est le serveur d'hébergement.
EN_LIGNE = Path("/mount/src").exists()

VOIES = {  # voie → (libellé court, icône, couleur de badge)
    "R&D interne (RDDC)": ("R&D interne", ":material/science:", "blue"),
    "Défi d'innovation IDEaS": ("Défi IDEaS", ":material/emoji_objects:", "green"),
    "Revue humaine approfondie": ("Revue humaine", ":material/groups:", "orange"),
}

AIDE_OLLAMA_CLOUD = """\
L'application est hébergée : elle ne peut pas joindre l'Ollama de votre poste par `localhost`.

- **Tunnel** : définissez `OLLAMA_BASE_URL` dans les secrets (adresse ngrok avec identifiants), ou saisissez-la ici.
- **Ollama Cloud** : adresse `https://ollama.com` et clé API.
- **Local** : lancez l'application sur votre poste (`streamlit run streamlit_app.py`).
"""


def secret(*noms: str, defaut: str = "") -> str:
    """Premier secret Streamlit (Cloud) ou variable d'environnement défini parmi `noms`."""
    for nom in noms:
        try:
            if nom in st.secrets:
                return str(st.secrets[nom])
        except FileNotFoundError:
            pass  # aucun fichier de secrets en local
        if os.environ.get(nom):
            return os.environ[nom]
    return defaut


@st.cache_data(ttl="1m", show_spinner=False)
def modeles_ollama(url: str, api_key: str) -> dict[str, list[str] | None]:
    return ClientOllama(url, 10, api_key).modeles()


@st.cache_data(show_spinner=False)
def titres_refs() -> dict[str, str]:
    return titres_references(Config())


# --------------------------------------------------------------------------- moteur (barre latérale)

def panneau_moteur() -> None:
    """Choix et état du moteur ; publie `config`, `moteur_pret` et `moteur_message` dans la session."""
    config = Config()
    cle_claude = secret("ANTHROPIC_API_KEY")
    if cle_claude:
        os.environ["ANTHROPIC_API_KEY"] = cle_claude
    url_secrets = secret("OLLAMA_BASE_URL", "OLLAMA_HOST")

    st.subheader("Moteur d'analyse", anchor=False)
    defaut = "ollama" if url_secrets or not cle_claude else "anthropic"
    choix = st.segmented_control("Moteur", ["ollama", "anthropic"], default=defaut, required=True,
                                 format_func={"ollama": "Ollama", "anthropic": "Claude"}.get,
                                 key="moteur_choix", width="stretch", label_visibility="collapsed")
    pret, message = False, ""

    if choix == "anthropic":
        effort = st.segmented_control("Effort de raisonnement", ["medium", "high", "xhigh"], default="high",
                                      required=True, key="effort",
                                      format_func={"medium": "Moyen", "high": "Élevé", "xhigh": "Très élevé"}.get)
        config = replace(config, fournisseur="anthropic", effort=effort)
        pret = bool(cle_claude)
        message = "Clé `ANTHROPIC_API_KEY` absente des secrets." if not pret else ""
    else:
        autre = False
        if url_secrets:
            st.caption(f"Serveur : `{masquer_identifiants(url_secrets)}`")
            autre = st.toggle("Utiliser une autre adresse", key="ollama_autre")
        url = url_secrets
        if not url_secrets or autre:
            url = st.text_input("Serveur Ollama", value="" if EN_LIGNE else "http://localhost:11434",
                                key="ollama_url", type="password" if EN_LIGNE else "default",
                                placeholder="https://utilisateur:motdepasse@xxxx.ngrok-free.app")
        api_key = secret("OLLAMA_API_KEY")
        disponibles: dict = {}
        if EN_LIGNE and (not url or est_adresse_locale(url)):
            message = "Ollama local inaccessible depuis l'hébergement."
            st.info(AIDE_OLLAMA_CLOUD, icon=":material/lan:")
        elif url:
            try:
                disponibles = modeles_ollama(url, api_key)
            except MoteurIndisponible as exc:
                message = str(exc)
        if disponibles:
            noms = list(disponibles)
            prefere = normaliser_modele(secret("OLLAMA_MODEL", "OLLAMA_MODELE", defaut=config.ollama_modele))
            modele = st.selectbox("Modèle", noms, index=noms.index(prefere) if prefere in noms else 0,
                                  key="ollama_modele")
            config = replace(config, fournisseur="ollama", ollama_url=url, ollama_modele=modele,
                             ollama_api_key=api_key,
                             ollama_num_ctx=int(secret("OLLAMA_NUM_CTX", defaut=str(config.ollama_num_ctx))))
            pret = True

    if pret:
        st.badge("Connecté", icon=":material/check_circle:", color="green")
        st.caption(libelle_moteur(config))
    else:
        st.badge("Indisponible", icon=":material/error:", color="red")
        if message and not (choix == "ollama" and EN_LIGNE and "hébergement" in message):
            st.caption(message)

    with st.expander("Règles d'escalade", icon=":material/rule:"):
        seuil = st.slider("Seuil de confiance", 0.0, 1.0, 0.70, 0.05, key="seuil",
                          help="Sous ce seuil, la recommandation est soumise à un humain.")
        st.caption("Sont aussi escaladés : dossiers ambigus, contradictoires, à risque élevé, et le Top 20 d'un lot.")
    config = replace(config, seuil_confiance=seuil)

    st.session_state.config = config
    st.session_state.moteur_pret = pret
    st.session_state.moteur_message = message or "Moteur indisponible."


# --------------------------------------------------------------------------- affichage d'un résultat

def badge_voie(voie: str) -> None:
    court, icone, couleur = VOIES.get(voie, (voie, ":material/help:", "gray"))
    st.badge(court, icon=icone, color=couleur)


def libelle_etape(trace: Trace) -> str:
    e = trace.entree
    libelles = {
        "rechercher_references": f"Recherche dans les références autorisées : « {e.get('requete', '')} »",
        "lire_reference": f"Lecture de la référence {e.get('id_reference', '')}",
        "consulter_dip": "Consultation de l'ERP (outil DIP) : projets connexes et budgets",
        "rechercher_demandes_similaires": f"Recherche de demandes antérieures : « {e.get('requete', '')} »",
        "soumettre_analyse": "Rédaction de l'analyse et de la recommandation",
    }
    if trace.statut == "refusé":
        return f"Action refusée par la politique de l'agent : {trace.outil}"
    return libelles.get(trace.outil, trace.outil)


def fiche(r: Resultat) -> None:
    """Fiche d'analyse d'un dossier, en éléments Streamlit natifs."""
    if r.escalade:
        st.error(" · ".join(r.motifs_escalade), title="Validation humaine requise", icon=":material/how_to_reg:")
    else:
        st.success("Recommandation enregistrée ; elle reste soumise à l'échantillonnage qualité.",
                   title="Traitement autonome (L3)", icon=":material/verified:")
    a = r.analyse
    if a is None:
        st.info(r.erreur or "Dossier non analysé.", title="Dossier non analysé par l'agent",
                icon=":material/block:")
        return

    st.markdown(a.resume_besoin)
    with st.container(horizontal=True):
        st.metric("R&D interne", a.scores_voies.rd_interne, border=True)
        st.metric("Défi IDEaS", a.scores_voies.ideas, border=True)
        st.metric("Priorité", a.priorite, border=True)
        st.metric("Confiance", f"{a.confiance:.2f}", border=True)
        st.metric("Maturité (TRL)", a.trl_estime, border=True)

    st.subheader("Justification", icon=":material/gavel:", anchor=False)
    st.markdown("\n".join(f"- {j}" for j in a.justification))
    st.caption(f"Priorité : {a.justification_priorite}")

    gauche, droite = st.columns(2)
    with gauche:
        st.subheader("Critères d'orientation", icon=":material/balance:", anchor=False)
        st.dataframe(pd.DataFrame([c.model_dump() for c in a.criteres]).rename(
            columns={"critere": "Critère", "evaluation": "Évaluation", "favorise": "Favorise"}),
            hide_index=True, alt="Critères d'orientation et voie favorisée")
    with droite:
        st.subheader("Risques", icon=":material/warning:", anchor=False)
        st.dataframe(pd.DataFrame([x.model_dump() for x in a.risques]).rename(
            columns={"description": "Risque", "niveau": "Niveau", "mitigation": "Mitigation"}),
            hide_index=True, alt="Risques potentiels et mitigations")

    cols = st.columns(3)
    for col, titre, icone, items in (
        (cols[0], "Zones grises", ":material/blur_on:", a.zones_grises),
        (cols[1], "Contradictions", ":material/compare_arrows:", a.contradictions),
        (cols[2], "Questions au demandeur", ":material/contact_support:", a.questions_ouvertes),
    ):
        with col.container(border=True, height="stretch"):
            st.markdown(f"{icone} **{titre}**")
            st.markdown("\n".join(f"- {i}" for i in items) if items else "_Aucun élément signalé._")

    refs = titres_refs()
    st.caption("Références citées : " + (" · ".join(f"{x} — {refs.get(x, x)}" for x in a.references_utilisees)
                                          or "aucune"))


def rapport(resultats: list[Resultat], config: Config, moteur: str, nom_fichier: str,
            mode_demo: bool = False, cle: str = "rapport", apercu: bool = True) -> None:
    """Téléchargement (et aperçu) du rapport imprimable."""
    html = construire_html(resultats, config, titres_refs(), mode_demo=mode_demo, moteur=moteur)
    with st.container(horizontal=True, vertical_alignment="center"):
        st.download_button("Télécharger le rapport", html, nom_fichier, "text/html", type="primary",
                           icon=":material/download:", key=f"{cle}_dl")
        st.caption("Ouvrez le fichier puis « Imprimer / Exporter en PDF » pour obtenir le PDF.")
    if apercu:
        st.iframe(html, height=900, alt="Aperçu du rapport d'analyse imprimable")


def entete_resultat(r: Resultat) -> None:
    with st.container(horizontal=True, vertical_alignment="center"):
        if r.analyse:
            badge_voie(r.analyse.voie_recommandee)
        st.badge("Validation humaine" if r.escalade else "Autonome (L3)",
                 icon=":material/how_to_reg:" if r.escalade else ":material/verified:",
                 color="red" if r.escalade else "green")
        st.badge(r.classification, icon=":material/shield:", color="gray")
        st.caption(f"{r.demande_id} · {r.demandeur} · {r.date_reception}")
