"""Plateforme « Analyse des besoins en innovation » — point d'entrée et navigation."""

import streamlit as st

from interface.commun import panneau_moteur

st.set_page_config(page_title="Analyse des besoins en innovation", page_icon="assets/icone.svg", layout="wide")
st.logo("assets/logo.svg", icon_image="assets/icone.svg", size="large")

# État propre à chaque utilisateur, partagé entre les pages
st.session_state.setdefault("historique", [])
st.session_state.setdefault("analyse_courante", None)

with st.sidebar:
    panneau_moteur()

page = st.navigation(
    [
        st.Page("app_pages/nouvelle_analyse.py", title="Nouvelle analyse", icon=":material/add_circle:", default=True),
        st.Page("app_pages/mes_analyses.py", title="Mes analyses", icon=":material/history:"),
        st.Page("app_pages/demonstration.py", title="Démonstration", icon=":material/folder_open:"),
        st.Page("app_pages/a_propos.py", title="À propos", icon=":material/info:"),
    ],
    position="top",
)
page.run()

st.caption("Prototype non officiel · programme RDDC · ne saisissez aucune information classifiée ni Protégé B. "
           "Les recommandations de l'agent ne sont pas engageantes et requièrent une validation humaine.")
