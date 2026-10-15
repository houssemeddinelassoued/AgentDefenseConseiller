import streamlit as st

from agent_besoins.moteurs import libelle_moteur

config = st.session_state.config

st.title("À propos de l'agent", anchor=False)
st.caption("Carte d'identité de l'agent « Analyse des Besoins en Innovation » et garde-fous appliqués.")

st.warning("Prototype de démonstration, non officiel. Il ne représente ni le ministère de la Défense nationale "
           "ni les Forces armées canadiennes, et ses recommandations ne sont pas engageantes.",
           icon=":material/info:")

gauche, droite = st.columns(2)
with gauche.container(border=True, height="stretch"):
    st.subheader("Mission", icon=":material/flag:", anchor=False)
    st.markdown("""
Analyser les besoins en soutien S&T des Forces armées canadiennes et recommander la meilleure voie
d'approvisionnement :

- :blue-badge[:material/science: R&D interne] centres de recherche RDDC ;
- :green-badge[:material/emoji_objects: Défi IDEaS] mise en concurrence d'innovateurs externes ;
- :orange-badge[:material/groups: Revue humaine] dossiers ambigus, hors portée S&T ou sensibles.
""")
    st.markdown("**Utilisateurs** : responsables et analystes du programme RDDC  \n"
                "**Volume ciblé** : environ 1 000 besoins par an, de 4 à 5 pages chacun  \n"
                "**Autonomie** : L3 avancé / L4 supervisé")
with droite.container(border=True, height="stretch"):
    st.subheader("Escalade vers un humain", icon=":material/how_to_reg:", anchor=False)
    st.markdown(f"""
- les 20 recommandations les plus prioritaires d'un lot (cas stratégiques) ;
- confiance inférieure à {config.seuil_confiance:.2f} ;
- dossier ambigu, contradictoire ou présentant un risque élevé ;
- classification au-delà de {' / '.join(config.classifications_autorisees)} : jamais transmis au modèle ;
- toute erreur ou tout refus du moteur.
""")
    st.markdown(f"**Moteur actuel** : {libelle_moteur(config)}")

gauche, droite = st.columns(2)
with gauche.container(border=True, height="stretch"):
    st.subheader("Actions permises", icon=":material/check_circle:", anchor=False)
    st.markdown("- Lire les demandes\n- Analyser le contenu\n- Formuler des recommandations\n"
                "- Souligner les risques potentiels\n- Prioriser et justifier les options\n"
                "- Enregistrer l'analyse dans la bibliothèque SharePoint prévue")
with droite.container(border=True, height="stretch"):
    st.subheader("Actions interdites", icon=":material/block:", anchor=False)
    st.markdown("- Effacer des données ou fichiers\n- Modifier la demande originale\n"
                "- Transmettre ailleurs que dans SharePoint\n- Lancer un projet ou un défi sans validation")
    st.caption("Impossibles par construction : l'agent ne dispose que d'outils de lecture ; tout autre outil est "
               "refusé et journalisé ; l'empreinte SHA-256 de chaque demande est vérifiée après l'analyse.")

with st.container(border=True):
    st.subheader("Sources consultées par l'agent", icon=":material/hub:", anchor=False)
    st.markdown("Références autorisées (critères d'orientation, programme IDEaS, capacités RDDC, politiques), "
                "ERP DIP (projets connexes, budgets), historique des demandes. Dans ce prototype, ces sources "
                "sont simulées par des fichiers fictifs ; SharePoint, l'outil DIP, Outlook et Teams se "
                "brancheront par Microsoft Graph et les API internes.")
    st.caption("Code source : github.com/houssemeddinelassoued/AgentDefenseConseiller")
