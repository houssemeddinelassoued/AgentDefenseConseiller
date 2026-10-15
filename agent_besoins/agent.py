"""Boucle agentique : une demande → enquête outillée → analyse structurée.

La boucle est indépendante du fournisseur (Claude ou Ollama local, voir `moteurs.py`).
"""

from __future__ import annotations

from pydantic import ValidationError

from .config import Config
from .connecteurs import ERPDip, References, SharePoint
from .modeles import Analyse, Demande, Resultat
from .moteurs import Appel, creer_moteur
from .outils import OUTIL_SOUMISSION, Executeur
from .prompts import message_demande

RELANCE_SOUMISSION = (
    "Votre analyse n'a pas été soumise. Appelez maintenant l'outil soumettre_analyse "
    "avec l'analyse complète de cette demande."
)


class AgentAnalyseBesoins:
    def __init__(self, config: Config, fabrique_conversation=None):
        self.config = config
        self.nouvelle_conversation = fabrique_conversation or creer_moteur(config)
        self.sharepoint = SharePoint(config)
        self.dip = ERPDip(config)
        self.references = References(config)

    def analyser(self, demande: Demande) -> Resultat:
        resultat = Resultat(
            demande_id=demande.id, titre=demande.titre, demandeur=demande.demandeur,
            classification=demande.classification, date_reception=demande.date_reception,
        )

        # Garde-fou : un dossier au-delà du niveau autorisé n'est jamais transmis au modèle.
        if demande.classification.upper() not in self.config.classifications_autorisees:
            resultat.erreur = (
                f"Classification « {demande.classification} » hors du périmètre autorisé : "
                "dossier non transmis au modèle, orienté directement vers un analyste habilité."
            )
            return resultat

        executeur = Executeur(self.sharepoint, self.dip, self.references)
        conversation = self.nouvelle_conversation()

        def compter(tour) -> None:
            resultat.jetons_entree += tour.jetons_entree
            resultat.jetons_sortie += tour.jetons_sortie

        def valider(entree: dict) -> str | None:
            try:
                resultat.analyse = Analyse(**{**entree, "id_demande": demande.id})
                return None
            except (ValidationError, TypeError) as exc:
                return f"Analyse invalide, corrigez et resoumettez : {exc}"

        if conversation.utilise_outils:
            conversation.ajouter_utilisateur(message_demande(demande))
            self._boucle_outils(conversation, executeur, resultat, compter, valider)
        else:
            # Modèle sans appel d'outils : le contexte est collecté d'avance (et journalisé).
            conversation.ajouter_utilisateur(message_demande(demande) + self._contexte_prealable(demande, executeur))

        if resultat.analyse is None and resultat.erreur is None:
            # Repli (modèles locaux) : sortie JSON imposée, une seconde tentative avec l'erreur en retour.
            for tentative in range(2):
                entree, tour = conversation.forcer_analyse()
                compter(tour)
                probleme = "JSON illisible." if entree is None else valider(entree)
                if probleme is None:
                    break
                if tentative == 0:
                    conversation.ajouter_utilisateur(f"Votre analyse a été rejetée : {probleme[:800]}")
                else:
                    resultat.erreur = f"L'agent n'a pas produit d'analyse valide : {probleme[:300]}"

        resultat.traces = executeur.traces
        return resultat

    def _boucle_outils(self, conversation, executeur, resultat, compter, valider) -> None:
        relance_faite = False
        for _ in range(self.config.max_iterations):
            tour = conversation.tour()
            compter(tour)
            if tour.arret in ("refus", "tronque"):
                resultat.erreur = tour.detail
                return
            if not tour.appels:
                if relance_faite:
                    return  # le repli forcer_analyse() prend le relais si le moteur le permet
                relance_faite = True
                conversation.ajouter_utilisateur(RELANCE_SOUMISSION)
                continue

            resultats_outils: list[tuple[Appel, str, bool]] = []
            for appel in tour.appels:
                contenu, est_erreur = executeur.executer(appel.nom, appel.entree)
                if appel.nom == OUTIL_SOUMISSION and not est_erreur:
                    if (probleme := valider(appel.entree)) is not None:
                        contenu, est_erreur = probleme, True
                resultats_outils.append((appel, contenu, est_erreur))
            conversation.ajouter_resultats(resultats_outils)

            if resultat.analyse is not None:
                return
        resultat.erreur = "Nombre maximal d'itérations atteint sans analyse."

    def _contexte_prealable(self, demande: Demande, executeur: Executeur) -> str:
        blocs = []
        for id_ref in self.references.ids():
            texte, _ = executeur.executer("lire_reference", {"id_reference": id_ref})
            blocs.append(f'<reference id="{id_ref}">\n{texte}\n</reference>')
        dip, _ = executeur.executer("consulter_dip", {"id_demande": demande.id})
        historique, _ = executeur.executer("rechercher_demandes_similaires", {"requete": demande.titre})
        return (
            "\n\nRéférences autorisées :\n" + "\n".join(blocs)
            + f"\n\nDonnées ERP DIP du dossier :\n{dip}"
            + f"\n\nDemandes antérieures similaires :\n{historique}"
        )
