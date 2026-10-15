"""Paramètres de l'agent « Analyse des Besoins en Innovation »."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Config:
    # Fournisseur du modèle : "anthropic" (Claude, API) ou "ollama" (modèle local)
    fournisseur: str = os.environ.get("AGENT_FOURNISSEUR", "anthropic")

    # Ollama local — les demandes ne quittent pas le poste
    ollama_url: str = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    ollama_modele: str = os.environ.get("OLLAMA_MODELE", "gemma4:latest")
    ollama_num_ctx: int = int(os.environ.get("OLLAMA_NUM_CTX", "32768"))
    ollama_timeout: float = 600.0  # un modèle local sur CPU peut être lent

    # Modèle Claude et profondeur de raisonnement
    modele: str = os.environ.get("AGENT_MODELE", "claude-opus-5-5")
    effort: str = os.environ.get("AGENT_EFFORT", "high")
    max_tokens: int = 16000
    max_iterations: int = 12  # tours d'outils maximum par demande

    # Sources (SharePoint simulé localement — remplacer par Microsoft Graph en production)
    dossier_demandes: Path = RACINE / "donnees" / "sharepoint" / "demandes"
    dossier_references: Path = RACINE / "donnees" / "references"
    fichier_dip: Path = RACINE / "donnees" / "erp_dip" / "dip.json"
    fichier_historique: Path = RACINE / "donnees" / "sharepoint" / "historique.json"

    # Seule destination d'écriture autorisée (bibliothèque SharePoint prévue)
    bibliotheque_analyses: Path = RACINE / "donnees" / "sharepoint" / "analyses"

    # Règles d'escalade (carte d'identité : Top 20 + faible confiance / ambigu / contradictoire / risque)
    top_n_validation: int = 20
    seuil_confiance: float = 0.70

    # Garde-fou de classification : au-delà, le dossier n'est jamais transmis au modèle
    classifications_autorisees: tuple[str, ...] = field(
        default=("NON CLASSIFIÉ", "PROTÉGÉ A")
    )
