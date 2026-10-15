from collections import Counter
from dataclasses import replace

import pandas as pd
import streamlit as st

from agent_besoins.config import Config
from agent_besoins.escalade import appliquer_escalade
from agent_besoins.pipeline import executer_demo
from interface.commun import VOIES, entete_resultat, fiche, rapport


@st.cache_data(show_spinner=False)
def lot_demo():
    return executer_demo(Config())


st.title("Dossiers de démonstration", anchor=False)
st.caption("Neuf demandes fictives et leurs analyses pré-calculées, pour découvrir la plateforme sans moteur.")

with st.container(horizontal=True, vertical_alignment="bottom"):
    st.warning("Demandes fictives ; analyses rédigées à titre d'illustration, sans appel au modèle.",
               icon=":material/science:", width="stretch")
    top_n = st.number_input("Top N soumis à validation", min_value=0, max_value=50, value=3, key="demo_top_n",
                            help="20 en production ; 3 pour ce lot de 9 dossiers.", width=220)

config = replace(st.session_state.config, top_n_validation=int(top_n))
# Les règles d'escalade s'appliquent à l'affichage : modifier le Top N ou le seuil ne relance rien.
resultats = appliquer_escalade([r.model_copy(deep=True) for r in lot_demo()], config)
analyses = [r for r in resultats if r.analyse]
ordonnes = sorted(resultats, key=lambda r: (r.rang_priorite is None, r.rang_priorite or 0))

n_escalade = sum(r.escalade for r in resultats)
with st.container(horizontal=True):
    st.metric("Demandes reçues", len(resultats), border=True)
    st.metric("Analysées par l'agent", len(analyses), border=True)
    st.metric("Validation humaine", n_escalade, border=True)
    st.metric("Confiance moyenne", f"{sum(r.analyse.confiance for r in analyses) / len(analyses):.2f}", border=True)

gauche, droite = st.columns(2)
with gauche.container(border=True, height="stretch"):
    st.markdown("**Répartition des voies recommandées**")
    voies = Counter(VOIES[r.analyse.voie_recommandee][0] for r in analyses)
    st.bar_chart(pd.DataFrame({"Voie": list(voies), "Dossiers": list(voies.values())}), x="Voie", y="Dossiers",
                 horizontal=True, height=200, alt="Nombre de dossiers par voie recommandée")
with droite.container(border=True, height="stretch"):
    st.markdown("**Motifs de validation humaine**")
    motifs = Counter(m.split(" (")[0].split(" :")[0] for r in resultats for m in r.motifs_escalade)
    st.dataframe(pd.DataFrame(motifs.most_common(), columns=["Motif", "Dossiers"]), hide_index=True,
                 alt="Motifs d'escalade et nombre de dossiers")

onglets = st.tabs([":material/format_list_numbered: Priorisation", ":material/description: Fiches",
                   ":material/fact_check: Traçabilité", ":material/print: Rapport du lot"])

with onglets[0]:
    st.dataframe(
        pd.DataFrame([{
            "Rang": r.rang_priorite, "Dossier": r.demande_id, "Besoin": r.titre,
            "Voie": VOIES[r.analyse.voie_recommandee][0] if r.analyse else "Non analysé",
            "Priorité": r.analyse.priorite if r.analyse else None,
            "Confiance": r.analyse.confiance if r.analyse else None,
            "Statut": "Validation humaine" if r.escalade else "Autonome (L3)",
            "Motifs": " · ".join(r.motifs_escalade),
        } for r in ordonnes]),
        hide_index=True, alt="Dossiers de démonstration classés par priorité",
        column_config={
            "Priorité": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%d"),
            "Confiance": st.column_config.ProgressColumn(min_value=0.0, max_value=1.0, format="%.2f"),
        },
    )

with onglets[1]:
    par_id = {r.demande_id: r for r in ordonnes}
    choisi = st.selectbox("Dossier", list(par_id), format_func=lambda i: f"{i} — {par_id[i].titre}", key="demo_fiche")
    r = par_id[choisi]
    st.markdown(f"### {r.titre}")
    entete_resultat(r)
    fiche(r)

with onglets[2]:
    st.dataframe(pd.DataFrame([{"Dossier": r.demande_id, "Intégrité de l'original": r.integrite_ok,
                                "Classification": r.classification} for r in resultats]),
                 hide_index=True, alt="Intégrité des demandes originales")
    st.caption("Mode démonstration : aucun appel d'outil n'est journalisé. Les empreintes SHA-256 des demandes "
               "sont réellement vérifiées.")

with onglets[3]:
    rapport(resultats, config, "Aucun (démonstration)", "rapport_demonstration.html", mode_demo=True, cle="demo")
