"""Modèles de données : demande de besoin, analyse produite par l'agent, décision d'escalade."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Voie = Literal["R&D interne (RDDC)", "Défi d'innovation IDEaS", "Revue humaine approfondie"]
Niveau = Literal["faible", "moyen", "élevé"]


class Demande(BaseModel):
    id: str
    titre: str
    date_reception: str
    demandeur: str
    classification: str
    contexte: dict = Field(default_factory=dict)
    parametres: dict = Field(default_factory=dict)
    contenu: str
    empreinte_sha256: str = ""  # calculée à la lecture, revérifiée en fin de traitement


class ScoresVoies(BaseModel):
    rd_interne: int = Field(ge=0, le=100)
    ideas: int = Field(ge=0, le=100)


class Critere(BaseModel):
    critere: str
    evaluation: str
    favorise: Literal["R&D interne", "IDEaS", "Neutre"]


class Risque(BaseModel):
    description: str
    niveau: Niveau
    mitigation: str


class Analyse(BaseModel):
    id_demande: str
    resume_besoin: str
    voie_recommandee: Voie
    scores_voies: ScoresVoies
    justification: list[str]
    criteres: list[Critere]
    risques: list[Risque]
    zones_grises: list[str]
    contradictions: list[str]
    questions_ouvertes: list[str]
    trl_estime: str
    priorite: int = Field(ge=0, le=100)
    justification_priorite: str
    confiance: float = Field(ge=0.0, le=1.0)
    references_utilisees: list[str]


class Trace(BaseModel):
    horodatage: str
    outil: str
    entree: dict
    statut: Literal["ok", "erreur", "refusé"]
    detail: str = ""


class Resultat(BaseModel):
    """Résultat complet pour une demande : analyse + escalade + traçabilité."""

    demande_id: str
    titre: str
    demandeur: str
    classification: str
    date_reception: str
    analyse: Analyse | None = None
    erreur: str | None = None
    rang_priorite: int | None = None
    escalade: bool = False
    motifs_escalade: list[str] = Field(default_factory=list)
    traces: list[Trace] = Field(default_factory=list)
    integrite_ok: bool | None = None
    jetons_entree: int = 0
    jetons_sortie: int = 0
