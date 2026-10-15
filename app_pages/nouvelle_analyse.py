import time
from datetime import datetime

import streamlit as st

from agent_besoins.config import Config
from agent_besoins.connecteurs import SharePoint
from agent_besoins.extraction import FORMATS, DocumentIllisible, extraire_texte
from agent_besoins.moteurs import MoteurIndisponible, libelle_moteur
from agent_besoins.pipeline import ErreurFatale, analyser_demande, creer_demande
from interface.commun import entete_resultat, fiche, libelle_etape, rapport

NIVEAUX = ["NON CLASSIFIÉ", "PROTÉGÉ A", "PROTÉGÉ B", "SECRET"]
SOURCES = {"document": ":material/upload_file: Téléverser un document", "texte": ":material/edit: Rédiger le besoin"}
GABARIT = """1. Contexte opérationnel —
2. Énoncé du problème —
3. Résultats attendus —
4. Contraintes (classification, données, partenaires) —
5. Calendrier, budget estimé, maturité actuelle et visée (TRL) —"""

config = st.session_state.config
autorises = config.classifications_autorisees


@st.cache_data(max_entries=20, show_spinner="Extraction du texte…")
def texte_du_document(nom: str, donnees: bytes) -> str:
    return extraire_texte(nom, donnees)


@st.cache_data(show_spinner=False)
def exemples() -> dict[str, dict]:
    sp = SharePoint(Config())
    demandes = (sp.lire_demande(p) for p in sp.lister_demandes())
    return {d.id: d.model_dump() for d in demandes if d.classification in Config().classifications_autorisees}


def charger_exemple() -> None:
    d = exemples()[st.session_state.exemple_choisi]
    st.session_state.f_titre = d["titre"]
    st.session_state.f_demandeur = d["demandeur"]
    st.session_state.f_classification = d["classification"]
    st.session_state.f_source = "texte"
    st.session_state.f_texte = d["contenu"]


def reinitialiser() -> None:
    for cle in ("f_titre", "f_demandeur", "f_texte", "f_fichier", "f_confirme", "exemple_choisi"):
        st.session_state.pop(cle, None)
    st.session_state.analyse_courante = None


st.session_state.setdefault("f_source", "document")
st.session_state.setdefault("f_classification", "NON CLASSIFIÉ")

st.title("Nouvelle analyse de besoin", anchor=False)
st.caption("Soumettez un besoin en soutien S&T : l'agent recommande la voie d'approvisionnement "
           "(R&D interne, défi IDEaS ou revue humaine) et produit un rapport imprimable.")

if not st.session_state.moteur_pret:
    st.warning(f"{st.session_state.moteur_message} Configurez le moteur dans le panneau latéral, ou consultez "
               "les dossiers de démonstration.", title="Moteur d'analyse indisponible", icon=":material/power_off:")

# --------------------------------------------------------------------------- 1. le besoin
with st.container(border=True):
    st.subheader("1. Décrire le besoin", icon=":material/edit_note:", anchor=False)
    with st.container(horizontal=True, vertical_alignment="bottom"):
        st.selectbox("Partir d'un exemple fictif (facultatif)", list(exemples()), index=None,
                     format_func=lambda i: f"{i} — {exemples()[i]['titre']}", key="exemple_choisi",
                     placeholder="Choisir une demande de démonstration")
        st.button("Charger l'exemple", icon=":material/content_copy:", on_click=charger_exemple,
                  disabled=not st.session_state.get("exemple_choisi"))

    titre = st.text_input("Titre du besoin", key="f_titre", max_chars=160,
                          placeholder="p. ex. Détection de mini-drones en environnement arctique")
    with st.container(horizontal=True, vertical_alignment="bottom"):
        demandeur = st.text_input("Organisation demandeuse", key="f_demandeur",
                                  placeholder="p. ex. Armée canadienne — Direction des besoins terrestres")
        classification = st.segmented_control("Classification", NIVEAUX, key="f_classification", required=True)

    autorise = classification in autorises
    contenu, source = "", ""
    if not autorise:
        st.error(f"L'agent ne traite que l'information {' ou '.join(autorises)}. Ne téléversez ni ne saisissez ce "
                 "contenu ici : transmettez le dossier à un analyste habilité par les voies sécurisées.",
                 title=f"Niveau « {classification} » hors périmètre", icon=":material/gpp_bad:")
    else:
        mode = st.segmented_control("Source", list(SOURCES), format_func=SOURCES.get, key="f_source",
                                    required=True, label_visibility="collapsed")
        if mode == "document":
            fichier = st.file_uploader("Document de demande (PDF, Word, texte)", type=FORMATS, key="f_fichier",
                                       max_upload_size=10, help="Le texte est extrait puis analysé ; 10 Mo maximum.")
            if fichier is not None:
                try:
                    contenu = texte_du_document(fichier.name, fichier.getvalue())
                    source = f"Document téléversé : {fichier.name}"
                    st.caption(f":material/check_circle: {len(contenu):,} caractères extraits de « {fichier.name} »")
                    with st.expander("Aperçu du texte extrait", icon=":material/visibility:"):
                        st.text(contenu[:5000] + ("\n[…]" if len(contenu) > 5000 else ""))
                except DocumentIllisible as exc:
                    st.error(str(exc), title="Document inutilisable", icon=":material/error:")
        else:
            contenu = st.text_area("Description du besoin", key="f_texte", height=320, placeholder=GABARIT,
                                   max_chars=80_000).strip()
            source = "Texte saisi dans la plateforme"
            if contenu and len(contenu) < 200:
                st.caption(":material/info: Ajoutez du détail (au moins 200 caractères) pour une analyse fiable.")

    confirme = st.checkbox(f"Je confirme que ce contenu est {' ou '.join(autorises)} et peut être transmis "
                           f"au moteur d'analyse ({libelle_moteur(config)}).", key="f_confirme", disabled=not autorise)

# --------------------------------------------------------------------------- 2. lancer
manques = [m for m, ok in (
    ("un titre", bool(titre and titre.strip())),
    ("un document ou une description d'au moins 200 caractères", len(contenu) >= 200),
    ("la confirmation de classification", confirme),
    ("un moteur disponible", st.session_state.moteur_pret),
) if not ok]
with st.container(horizontal=True, vertical_alignment="center"):
    lancer = st.button("Analyser le besoin", type="primary", icon=":material/neurology:",
                       disabled=bool(manques) or not autorise)
    st.button("Réinitialiser", icon=":material/restart_alt:", on_click=reinitialiser)
    if manques and autorise:
        st.caption("Il manque : " + ", ".join(manques) + ".")

if lancer:
    demande = creer_demande(titre, contenu, demandeur, classification, source)
    debut = time.monotonic()
    with st.status(":shimmer[L'agent analyse le besoin…]", expanded=True) as statut:
        st.caption(f"Moteur : {libelle_moteur(config)} · {len(contenu):,} caractères")

        def observateur(trace):
            etat = "complete" if trace.statut == "ok" else "error"
            with st.status(libelle_etape(trace), type="step", state=etat):
                if trace.detail:
                    st.caption(trace.detail)

        try:
            resultat = analyser_demande(config, demande, observateur=observateur)
        except (MoteurIndisponible, ErreurFatale) as exc:
            statut.update(label="Analyse impossible", state="error")
            st.error(str(exc))
            st.stop()
        duree = time.monotonic() - debut
        statut.update(label=f"Analyse terminée en {duree:.0f} s", state="complete", expanded=False)

    st.session_state.historique.append({
        "resultat": resultat, "moteur": libelle_moteur(config), "source": source,
        "horodatage": f"{datetime.now():%Y-%m-%d %H:%M}", "duree": duree, "contenu": contenu,
    })
    st.session_state.analyse_courante = len(st.session_state.historique) - 1
    st.toast("Analyse terminée : le rapport est prêt.", icon=":material/task_alt:")

# --------------------------------------------------------------------------- 3. résultat
indice = st.session_state.get("analyse_courante")
if indice is not None and indice < len(st.session_state.historique):
    entree = st.session_state.historique[indice]
    r = entree["resultat"]
    with st.container(border=True):
        st.subheader("2. Résultat de l'analyse", icon=":material/assignment_turned_in:", anchor=False)
        st.markdown(f"### {r.analyse.voie_recommandee if r.analyse else 'Dossier non analysé'}")
        entete_resultat(r)
        onglet_fiche, onglet_rapport, onglet_texte = st.tabs([
            ":material/description: Fiche d'analyse", ":material/print: Rapport imprimable",
            ":material/article: Texte soumis",
        ])
        with onglet_fiche:
            fiche(r)
        with onglet_rapport:
            rapport([r], config, entree["moteur"], f"rapport_{r.demande_id}.html", cle=f"nouv_{indice}")
        with onglet_texte:
            st.caption(entree["source"])
            st.text(entree["contenu"])
