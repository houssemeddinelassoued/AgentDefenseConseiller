"""Application Streamlit — agent « Analyse des Besoins en Innovation » (Programme RDDC)."""

from __future__ import annotations

import os
from collections import Counter
from dataclasses import replace

import pandas as pd
import streamlit as st

from agent_besoins.config import Config
from agent_besoins.escalade import appliquer_escalade
from agent_besoins.modeles import Resultat
from agent_besoins.moteurs import ClientOllama, MoteurIndisponible, libelle_moteur
from agent_besoins.pipeline import ErreurFatale, executer_analyse, executer_demo, titres_references
from agent_besoins.rapport import construire_html

st.set_page_config(page_title="Analyse des besoins en innovation", page_icon=":material/biotech:", layout="wide")

# Clé Anthropic : secrets Streamlit (Cloud) ou variable d'environnement (poste local)
try:
    if "ANTHROPIC_API_KEY" in st.secrets and not os.environ.get("ANTHROPIC_API_KEY"):
        os.environ["ANTHROPIC_API_KEY"] = st.secrets["ANTHROPIC_API_KEY"]
except FileNotFoundError:
    pass  # aucun fichier de secrets en local

MOTEURS = {"demo": "Démonstration", "anthropic": "Claude (API)", "ollama": "Ollama (local)"}
VOIES_COURTES = {
    "R&D interne (RDDC)": "R&D interne",
    "Défi d'innovation IDEaS": "Défi IDEaS",
    "Revue humaine approfondie": "Revue humaine",
}


@st.cache_data(ttl="1m", show_spinner=False)
def modeles_ollama(url: str) -> dict[str, list[str]]:
    return ClientOllama(url, 5).modeles()


@st.cache_data(show_spinner=False)
def titres_refs() -> dict[str, str]:
    return titres_references(Config())


def lot_demo() -> dict:
    return {"resultats": executer_demo(Config()), "mode_demo": True, "moteur": "Aucun (démonstration)"}


st.session_state.setdefault("lot", None)
if st.session_state.lot is None:
    st.session_state.lot = lot_demo()

# --------------------------------------------------------------------------- barre latérale
with st.sidebar:
    st.header("Paramètres", divider="blue")
    mode = st.segmented_control("Moteur", list(MOTEURS), format_func=MOTEURS.get, default="demo",
                                required=True, key="mode", width="stretch")
    config = Config()

    if mode == "anthropic":
        effort = st.segmented_control("Effort de raisonnement", ["medium", "high", "xhigh"], default="high",
                                      required=True, key="effort")
        config = replace(config, fournisseur="anthropic", effort=effort)
        if not os.environ.get("ANTHROPIC_API_KEY"):
            st.warning("Ajoutez `ANTHROPIC_API_KEY` aux secrets de l'application pour activer Claude.",
                       title="Clé API absente", icon=":material/key_off:")
    elif mode == "ollama":
        url = st.text_input("Serveur Ollama", value=config.ollama_url, key="ollama_url")
        try:
            disponibles = modeles_ollama(url)
        except MoteurIndisponible as exc:
            disponibles = {}
            st.error(str(exc), title="Ollama injoignable", icon=":material/cloud_off:")
            st.caption("Sur Streamlit Cloud, `localhost` désigne le serveur de Streamlit : exposez votre "
                       "Ollama par une adresse accessible ou exécutez l'application en local.")
        if disponibles:
            noms = list(disponibles)
            modele = st.selectbox(
                "Modèle", noms, key="ollama_modele",
                index=noms.index(config.ollama_modele) if config.ollama_modele in noms else 0,
                format_func=lambda n: f"{n} · {'outils' if 'tools' in disponibles[n] else 'JSON seul'}",
            )
            config = replace(config, fournisseur="ollama", ollama_url=url, ollama_modele=modele)

    st.subheader("Règles d'escalade")
    top_n = st.number_input("Top N soumis à validation", min_value=0, max_value=1000, value=3, key="top_n",
                            help="20 en production ; 3 pour un lot de démonstration de 9 dossiers.")
    seuil = st.slider("Seuil de confiance", 0.0, 1.0, 0.70, 0.05, key="seuil")
    config = replace(config, top_n_validation=int(top_n), seuil_confiance=seuil)

    pret = mode == "demo" or (mode == "anthropic" and os.environ.get("ANTHROPIC_API_KEY")) or \
        (mode == "ollama" and config.fournisseur == "ollama")
    limite = None
    if mode != "demo":
        limite = st.number_input("Nombre de demandes à analyser", min_value=1, max_value=9, value=9, key="limite")
    lancer = st.button("Lancer l'analyse", type="primary", icon=":material/play_arrow:", width="stretch",
                       disabled=not pret)

# --------------------------------------------------------------------------- exécution
if lancer:
    if mode == "demo":
        st.session_state.lot = lot_demo()
    else:
        with st.status(f"Analyse en cours — {libelle_moteur(config)}", expanded=True) as statut:
            def progression(rang, total, demande, resultat, secondes):
                if resultat is None:
                    statut.update(label=f"Dossier {rang}/{total} : {demande.titre}")
                else:
                    issue = resultat.analyse.voie_recommandee if resultat.analyse else f"non analysé — {resultat.erreur}"
                    st.write(f"**{demande.id}** → {issue} ({secondes:.0f} s)")

            try:
                resultats = executer_analyse(config, int(limite), progression=progression)
                st.session_state.lot = {"resultats": resultats, "mode_demo": False, "moteur": libelle_moteur(config)}
                statut.update(label="Analyse terminée", state="complete", expanded=False)
            except (MoteurIndisponible, ErreurFatale) as exc:
                statut.update(label="Analyse interrompue", state="error")
                st.error(str(exc))

lot = st.session_state.lot
# Les règles d'escalade s'appliquent à l'affichage : modifier Top N ou le seuil ne relance pas l'analyse.
resultats: list[Resultat] = appliquer_escalade([r.model_copy(deep=True) for r in lot["resultats"]], config)
analyses = [r for r in resultats if r.analyse]

# --------------------------------------------------------------------------- en-tête et indicateurs
st.title("Analyse des besoins en innovation")
st.caption(f"Programme RDDC · Ministère de la Défense nationale · Moteur : {lot['moteur']}")
if lot["mode_demo"]:
    st.warning("Demandes fictives et analyses pré-calculées à titre d'illustration ; aucun appel au modèle.",
               title="Démonstration", icon=":material/science:")

n_escalade = sum(r.escalade for r in resultats)
confiance = sum(r.analyse.confiance for r in analyses) / len(analyses) if analyses else 0.0
with st.container(horizontal=True):
    st.metric("Demandes reçues", len(resultats), border=True)
    st.metric("Analysées par l'agent", len(analyses), border=True)
    st.metric("Validation humaine", n_escalade, border=True)
    st.metric("Confiance moyenne", f"{confiance:.2f}", border=True)

gauche, droite = st.columns(2)
with gauche.container(border=True, height="stretch"):
    st.markdown("**Répartition des voies recommandées**")
    voies = Counter(VOIES_COURTES[r.analyse.voie_recommandee] for r in analyses)
    st.bar_chart(pd.DataFrame({"Voie": list(voies), "Dossiers": list(voies.values())}),
                 x="Voie", y="Dossiers", horizontal=True, height=220, alt="Nombre de dossiers par voie recommandée")
with droite.container(border=True, height="stretch"):
    st.markdown("**Motifs de validation humaine**")
    motifs = Counter(m.split(" (")[0].split(" :")[0] for r in resultats for m in r.motifs_escalade)
    st.dataframe(pd.DataFrame(motifs.most_common(), columns=["Motif", "Dossiers"]), hide_index=True,
                 alt="Motifs d'escalade et nombre de dossiers")

# --------------------------------------------------------------------------- onglets
ordonnes = sorted(resultats, key=lambda r: (r.rang_priorite is None, r.rang_priorite or 0))
priorisation, humaine, fiches, tracabilite, rapport = st.tabs([
    ":material/format_list_numbered: Priorisation", ":material/how_to_reg: Validation humaine",
    ":material/description: Fiches", ":material/fact_check: Traçabilité", ":material/print: Rapport",
])

with priorisation:
    st.dataframe(
        pd.DataFrame([{
            "Rang": r.rang_priorite, "Dossier": r.demande_id, "Besoin": r.titre,
            "Voie": VOIES_COURTES[r.analyse.voie_recommandee] if r.analyse else "Non analysé",
            "Priorité": r.analyse.priorite if r.analyse else None,
            "Confiance": r.analyse.confiance if r.analyse else None,
            "Statut": "Validation humaine" if r.escalade else "Autonome (L3)",
        } for r in ordonnes]),
        hide_index=True, alt="Dossiers classés par priorité",
        column_config={
            "Priorité": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%d"),
            "Confiance": st.column_config.ProgressColumn(min_value=0.0, max_value=1.0, format="%.2f"),
        },
    )

with humaine:
    st.dataframe(
        pd.DataFrame([{"Dossier": r.demande_id, "Besoin": r.titre, "Motifs": " · ".join(r.motifs_escalade)}
                      for r in ordonnes if r.escalade]),
        hide_index=True, alt="Dossiers à valider par un humain et motifs",
    )

with fiches:
    par_id = {r.demande_id: r for r in ordonnes}
    choisi = st.selectbox("Dossier", list(par_id), format_func=lambda i: f"{i} — {par_id[i].titre}", key="fiche")
    choix = par_id[choisi]
    st.caption(f"{choix.demandeur} · reçue le {choix.date_reception} · {choix.classification}")
    if choix.escalade:
        st.error(" · ".join(choix.motifs_escalade), title="Validation humaine requise", icon=":material/how_to_reg:")
    else:
        st.success("Recommandation enregistrée, soumise à l'échantillonnage qualité.",
                   title="Traitement autonome (L3)", icon=":material/check_circle:")
    a = choix.analyse
    if a:
        st.subheader(a.voie_recommandee)
        st.write(a.resume_besoin)
        with st.container(horizontal=True):
            st.metric("R&D interne", a.scores_voies.rd_interne, border=True)
            st.metric("Défi IDEaS", a.scores_voies.ideas, border=True)
            st.metric("Priorité", a.priorite, border=True)
            st.metric("Confiance", f"{a.confiance:.2f}", border=True)
            st.metric("Maturité", a.trl_estime, border=True)
        st.markdown("**Justification**")
        st.markdown("\n".join(f"- {j}" for j in a.justification))
        st.caption(f"Priorité : {a.justification_priorite}")
        st.markdown("**Critères d'orientation**")
        st.dataframe(pd.DataFrame([c.model_dump() for c in a.criteres]).rename(
            columns={"critere": "Critère", "evaluation": "Évaluation", "favorise": "Favorise"}),
            hide_index=True, alt="Critères d'orientation")
        st.markdown("**Risques**")
        st.dataframe(pd.DataFrame([x.model_dump() for x in a.risques]).rename(
            columns={"description": "Risque", "niveau": "Niveau", "mitigation": "Mitigation"}),
            hide_index=True, alt="Risques et mitigations")
        col1, col2, col3 = st.columns(3)
        for col, titre, items in ((col1, "Zones grises", a.zones_grises), (col2, "Contradictions", a.contradictions),
                                  (col3, "Questions au demandeur", a.questions_ouvertes)):
            with col.container(border=True, height="stretch"):
                st.markdown(f"**{titre}**")
                st.markdown("\n".join(f"- {i}" for i in items) if items else "_Aucun élément._")
        refs = titres_refs()
        st.caption("Références : " + " · ".join(f"{r} — {refs.get(r, r)}" for r in a.references_utilisees))
    else:
        st.info(choix.erreur or "Dossier non analysé.", title="Dossier non analysé par l'agent")

with tracabilite:
    st.dataframe(pd.DataFrame([{"Dossier": r.demande_id, "Intégrité de l'original": r.integrite_ok,
                                "Jetons entrée": r.jetons_entree, "Jetons sortie": r.jetons_sortie}
                               for r in resultats]), hide_index=True, alt="Intégrité et consommation par dossier")
    traces = [{"Dossier": r.demande_id, "Horodatage (UTC)": t.horodatage, "Outil": t.outil,
               "Statut": t.statut, "Paramètres": str(t.entree)[:120]} for r in resultats for t in r.traces]
    if traces:
        st.dataframe(pd.DataFrame(traces), hide_index=True, alt="Journal des appels d'outils")
    else:
        st.info("Aucun appel d'outil dans ce lot (mode démonstration ou dossiers non transmis).")

with rapport:
    html = construire_html(resultats, config, titres_refs(), mode_demo=lot["mode_demo"], moteur=lot["moteur"])
    with st.container(horizontal=True, vertical_alignment="center"):
        st.download_button("Télécharger le rapport HTML", html, "rapport_analyse_besoins.html", "text/html",
                           icon=":material/download:", type="primary")
        st.caption("Pour le PDF : ouvrez le fichier et utilisez « Imprimer / Exporter en PDF ».")
    st.iframe(html, height=900, alt="Aperçu du rapport d'analyse imprimable")
