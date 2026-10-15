"""Orchestration d'un lot de demandes, partagée par la ligne de commande et l'application Streamlit."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Callable

from .config import RACINE, Config
from .connecteurs import References, SharePoint
from .escalade import appliquer_escalade
from .modeles import Analyse, Demande, Resultat
from .moteurs import MoteurIndisponible

FICHIER_EXEMPLES = RACINE / "exemples" / "analyses_demo.json"

# progression(rang, total, demande, resultat_ou_None, secondes) : None au début du dossier
Progression = Callable[[int, int, Demande, Resultat | None, float], None]


class ErreurFatale(RuntimeError):
    """Erreur qui interrompt tout le lot (p. ex. identifiants invalides)."""


def _hors_perimetre(d: Demande, config: Config) -> str | None:
    if d.classification.upper() in config.classifications_autorisees:
        return None
    return (f"Classification « {d.classification} » hors du périmètre autorisé : dossier non "
            "transmis au modèle, orienté directement vers un analyste habilité.")


def _resultat_vide(d: Demande, erreur: str | None = None) -> Resultat:
    return Resultat(demande_id=d.id, titre=d.titre, demandeur=d.demandeur,
                    classification=d.classification, date_reception=d.date_reception, erreur=erreur)


def _erreurs_moteur(config: Config) -> tuple[tuple[type[Exception], ...], tuple[type[Exception], ...]]:
    """(erreurs fatales, erreurs propres à un dossier) selon le fournisseur."""
    if config.fournisseur == "ollama":
        return (), (MoteurIndisponible,)
    import anthropic

    return (anthropic.AuthenticationError,), (anthropic.RateLimitError, anthropic.APIConnectionError,
                                              anthropic.APIStatusError)


def executer_analyse(config: Config, limite: int | None = None,
                     progression: Progression | None = None) -> list[Resultat]:
    """Analyse réelle par le moteur configuré. Lève MoteurIndisponible ou ErreurFatale."""
    from .agent import AgentAnalyseBesoins

    agent = AgentAnalyseBesoins(config)
    fatales, par_dossier = _erreurs_moteur(config)

    resultats = []
    chemins = agent.sharepoint.lister_demandes()[:limite]
    for i, chemin in enumerate(chemins, start=1):
        demande = agent.sharepoint.lire_demande(chemin)
        if progression:
            progression(i, len(chemins), demande, None, 0.0)
        debut = time.monotonic()
        try:
            resultat = agent.analyser(demande)
        except fatales as exc:
            raise ErreurFatale("Identifiants Anthropic invalides ou absents (ANTHROPIC_API_KEY).") from exc
        except par_dossier as exc:
            # Dossier escaladé plutôt que perdu ; les autres demandes continuent.
            resultat = _resultat_vide(demande, f"Erreur du moteur : {exc.__class__.__name__} — {str(exc)[:200]}")
        resultat.integrite_ok = agent.sharepoint.verifier_integrite(chemin, demande.empreinte_sha256)
        resultats.append(resultat)
        if progression:
            progression(i, len(chemins), demande, resultat, time.monotonic() - debut)

    appliquer_escalade(resultats, config)
    for r in resultats:  # seule écriture autorisée : la bibliothèque SharePoint prévue
        agent.sharepoint.enregistrer_analyse(f"{r.demande_id}_analyse.json", r.model_dump_json(indent=2))
    return resultats


def executer_demo(config: Config, fichier: Path = FICHIER_EXEMPLES) -> list[Resultat]:
    """Rejoue des analyses pré-calculées (aucun appel au modèle) pour illustrer le rapport."""
    sharepoint = SharePoint(config)
    exemples = {a["id_demande"]: a for a in json.loads(fichier.read_text(encoding="utf-8"))["analyses"]}
    resultats = []
    for chemin in sharepoint.lister_demandes():
        d = sharepoint.lire_demande(chemin)
        r = _resultat_vide(d, _hors_perimetre(d, config))
        if r.erreur is None:
            if d.id in exemples:
                r.analyse = Analyse(**exemples[d.id])
            else:
                r.erreur = "Aucune analyse de démonstration pour ce dossier."
        r.integrite_ok = sharepoint.verifier_integrite(chemin, d.empreinte_sha256)
        resultats.append(r)
    return appliquer_escalade(resultats, config)


def creer_demande(titre: str, contenu: str, demandeur: str, classification: str,
                  source: str, contexte: dict | None = None) -> Demande:
    """Demande soumise depuis l'interface (texte rédigé ou document téléversé)."""
    maintenant = datetime.now()
    return Demande(
        id=f"SOUM-{maintenant:%Y%m%d-%H%M%S}",
        titre=titre.strip(),
        date_reception=f"{maintenant:%Y-%m-%d}",
        demandeur=demandeur.strip() or "Non précisé",
        classification=classification,
        contexte={"source": source, **(contexte or {})},
        contenu=contenu,
        empreinte_sha256=hashlib.sha256(contenu.encode("utf-8")).hexdigest(),
    )


def analyser_demande(config: Config, demande: Demande, observateur=None) -> Resultat:
    """Analyse une demande isolée. Le Top N ne s'applique pas hors d'un lot ; les autres règles, si.

    Lève MoteurIndisponible ou ErreurFatale si le moteur est inutilisable.
    """
    from .agent import AgentAnalyseBesoins

    contenu_initial = demande.contenu
    hors = _hors_perimetre(demande, config)
    if hors:
        resultat = _resultat_vide(demande, hors)
    else:
        agent = AgentAnalyseBesoins(config)
        fatales, par_dossier = _erreurs_moteur(config)
        try:
            resultat = agent.analyser(demande, observateur=observateur)
        except fatales as exc:
            raise ErreurFatale("Identifiants Anthropic invalides ou absents (ANTHROPIC_API_KEY).") from exc
        except par_dossier as exc:
            resultat = _resultat_vide(demande, f"Erreur du moteur : {str(exc)[:300]}")
        agent.sharepoint.enregistrer_analyse(f"{demande.id}_analyse.json", resultat.model_dump_json(indent=2))
    resultat.integrite_ok = (
        demande.contenu == contenu_initial
        and hashlib.sha256(demande.contenu.encode("utf-8")).hexdigest() == demande.empreinte_sha256
    )
    appliquer_escalade([resultat], replace(config, top_n_validation=0))
    return resultat


def titres_references(config: Config) -> dict[str, str]:
    references = References(config)
    return {i: references.titre(i) for i in references.ids()}
