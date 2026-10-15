from dataclasses import replace

import pandas as pd
import streamlit as st

from agent_besoins.escalade import appliquer_escalade
from interface.commun import VOIES, entete_resultat, fiche, rapport

historique = st.session_state.historique
config = st.session_state.config

st.title("Mes analyses", anchor=False)
st.caption("Analyses réalisées pendant cette session. Téléchargez les rapports pour les conserver : "
           "la session n'est pas enregistrée après fermeture de la page.")

if not historique:
    st.info("Aucune analyse pour l'instant. Soumettez un besoin depuis « Nouvelle analyse » ou consultez les "
            "dossiers de démonstration.", icon=":material/inbox:")
    st.stop()

tableau = pd.DataFrame([{
    "Soumis le": e["horodatage"],
    "Dossier": e["resultat"].demande_id,
    "Besoin": e["resultat"].titre,
    "Voie": VOIES[e["resultat"].analyse.voie_recommandee][0] if e["resultat"].analyse else "Non analysé",
    "Confiance": e["resultat"].analyse.confiance if e["resultat"].analyse else None,
    "Statut": "Validation humaine" if e["resultat"].escalade else "Autonome (L3)",
    "Moteur": e["moteur"],
} for e in reversed(historique)])

selection = st.dataframe(
    tableau, hide_index=True, on_select="rerun", selection_mode="single-row", key="historique_table",
    alt="Analyses de la session",
    column_config={"Confiance": st.column_config.ProgressColumn(min_value=0.0, max_value=1.0, format="%.2f")},
)

with st.container(horizontal=True, vertical_alignment="center"):
    st.caption("Sélectionnez une ligne pour afficher la fiche et le rapport.")
    # Classement commun à toutes les analyses de la session (le Top N ne s'applique qu'à un lot officiel).
    consolide = appliquer_escalade([e["resultat"].model_copy(deep=True) for e in historique],
                                   replace(config, top_n_validation=0))
    with st.popover("Rapport consolidé de la session", icon=":material/library_books:"):
        st.caption(f"{len(consolide)} analyse(s) dans un seul rapport imprimable, classées par priorité.")
        rapport(consolide, replace(config, top_n_validation=0), "Analyses de la session",
                "rapport_session.html", cle="session", apercu=False)

lignes = selection.selection.rows
if lignes:
    entree = list(reversed(historique))[lignes[0]]
    r = entree["resultat"]
    with st.container(border=True):
        st.markdown(f"### {r.titre}")
        entete_resultat(r)
        onglet_fiche, onglet_rapport = st.tabs([":material/description: Fiche d'analyse",
                                                ":material/print: Rapport imprimable"])
        with onglet_fiche:
            fiche(r)
        with onglet_rapport:
            rapport([r], config, entree["moteur"], f"rapport_{r.demande_id}.html", cle=f"hist_{r.demande_id}")
