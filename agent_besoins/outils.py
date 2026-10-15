"""Outils exposés au modèle et politique d'actions (permises / interdites).

Le modèle ne dispose QUE d'outils de lecture et d'un outil de soumission de l'analyse.
Aucun outil ne permet d'effacer, de modifier une demande, de transmettre ailleurs que
dans SharePoint ou de lancer un projet : ces actions interdites sont impossibles par
construction, et toute tentative d'appeler un outil inconnu est refusée et journalisée.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Callable

from .connecteurs import ERPDip, References, SharePoint
from .modeles import Trace

OUTIL_SOUMISSION = "soumettre_analyse"

_CHAINE = {"type": "string"}
_LISTE = {"type": "array", "items": {"type": "string"}}

OUTILS = [
    {
        "name": "rechercher_references",
        "description": (
            "Recherche par mots-clés dans le corpus de références autorisées (critères RDDC/IDEaS, "
            "capacités des centres RDDC, politiques). Retourne les identifiants et des extraits. "
            "Utiliser pour fonder chaque recommandation sur une référence citée."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"requete": {"type": "string", "description": "Mots-clés en français."}},
            "required": ["requete"],
            "additionalProperties": False,
        },
    },
    {
        "name": "lire_reference",
        "description": "Retourne le texte intégral d'une référence autorisée à partir de son identifiant.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"id_reference": {"type": "string"}},
            "required": ["id_reference"],
            "additionalProperties": False,
        },
    },
    {
        "name": "consulter_dip",
        "description": (
            "Consulte l'ERP (outil DIP) en lecture seule : projets connexes, budget prévisionnel, "
            "jalons et code de programme liés au dossier. Utile pour détecter les chevauchements."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"id_demande": {"type": "string"}},
            "required": ["id_demande"],
            "additionalProperties": False,
        },
    },
    {
        "name": "rechercher_demandes_similaires",
        "description": (
            "Recherche dans l'historique SharePoint des demandes antérieures similaires et la voie "
            "finalement retenue par les experts. Sert à la cohérence des recommandations."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"requete": {"type": "string"}},
            "required": ["requete"],
            "additionalProperties": False,
        },
    },
    {
        "name": OUTIL_SOUMISSION,
        "description": (
            "Soumet l'analyse finale du besoin. À appeler exactement une fois, à la fin, "
            "lorsque l'analyse est complète. La recommandation reste non engageante : elle "
            "sera enregistrée dans SharePoint et, si requis, validée par un humain."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "id_demande": _CHAINE,
                "resume_besoin": {"type": "string", "description": "Synthèse du besoin en 3 à 5 phrases."},
                "voie_recommandee": {
                    "type": "string",
                    "enum": ["R&D interne (RDDC)", "Défi d'innovation IDEaS", "Revue humaine approfondie"],
                },
                "scores_voies": {
                    "type": "object",
                    "description": "Adéquation de 0 à 100 de chaque voie.",
                    "properties": {"rd_interne": {"type": "integer"}, "ideas": {"type": "integer"}},
                    "required": ["rd_interne", "ideas"],
                    "additionalProperties": False,
                },
                "justification": {**_LISTE, "description": "Arguments principaux, chacun appuyé sur la demande ou une référence."},
                "criteres": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "critere": _CHAINE,
                            "evaluation": _CHAINE,
                            "favorise": {"type": "string", "enum": ["R&D interne", "IDEaS", "Neutre"]},
                        },
                        "required": ["critere", "evaluation", "favorise"],
                        "additionalProperties": False,
                    },
                },
                "risques": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "description": _CHAINE,
                            "niveau": {"type": "string", "enum": ["faible", "moyen", "élevé"]},
                            "mitigation": _CHAINE,
                        },
                        "required": ["description", "niveau", "mitigation"],
                        "additionalProperties": False,
                    },
                },
                "zones_grises": {**_LISTE, "description": "Éléments flous ou manquants qui limitent la décision."},
                "contradictions": {**_LISTE, "description": "Incohérences internes à la demande (liste vide si aucune)."},
                "questions_ouvertes": {**_LISTE, "description": "Questions à poser au demandeur."},
                "trl_estime": {"type": "string", "description": "Niveau de maturité technologique actuel et visé, ex. « TRL 3 → 6 »."},
                "priorite": {"type": "integer", "description": "Priorité de 0 à 100 (impact opérationnel × urgence × faisabilité)."},
                "justification_priorite": _CHAINE,
                "confiance": {"type": "number", "description": "Confiance de 0.0 à 1.0 dans la recommandation."},
                "references_utilisees": {**_LISTE, "description": "Identifiants des références consultées et citées."},
            },
            "required": [
                "id_demande", "resume_besoin", "voie_recommandee", "scores_voies", "justification",
                "criteres", "risques", "zones_grises", "contradictions", "questions_ouvertes",
                "trl_estime", "priorite", "justification_priorite", "confiance", "references_utilisees",
            ],
            "additionalProperties": False,
        },
    },
]

OUTILS_AUTORISES = frozenset(o["name"] for o in OUTILS)


class Executeur:
    """Exécute les appels d'outils du modèle en appliquant la politique d'actions et journalise tout."""

    def __init__(self, sharepoint: SharePoint, dip: ERPDip, references: References,
                 observateur: Callable[[Trace], None] | None = None):
        self.sharepoint = sharepoint
        self.dip = dip
        self.references = references
        self.traces: list[Trace] = []
        self.observateur = observateur  # p. ex. l'interface qui affiche les étapes en direct

    def _tracer(self, outil: str, entree: dict, statut: str, detail: str = "") -> None:
        self.traces.append(Trace(
            horodatage=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            outil=outil, entree=entree, statut=statut, detail=detail[:300],
        ))
        if self.observateur:
            self.observateur(self.traces[-1])

    def executer(self, nom: str, entree: dict) -> tuple[str, bool]:
        """Retourne (contenu du tool_result, est_erreur)."""
        if nom not in OUTILS_AUTORISES:
            self._tracer(nom, entree, "refusé", "Outil hors de la politique d'actions permises.")
            return f"Action refusée : l'outil « {nom} » n'est pas autorisé pour cet agent.", True
        try:
            resultat = self._dispatcher(nom, entree)
        except Exception as exc:  # erreur de connecteur : renvoyée au modèle, pas d'arrêt
            self._tracer(nom, entree, "erreur", str(exc))
            return f"Erreur : {exc}", True
        self._tracer(nom, entree, "ok")
        return resultat, False

    def _dispatcher(self, nom: str, entree: dict) -> str:
        if nom == "rechercher_references":
            res = self.references.rechercher(entree["requete"])
            return json.dumps(res or {"message": "Aucune référence trouvée.", "disponibles": self.references.ids()},
                              ensure_ascii=False)
        if nom == "lire_reference":
            texte = self.references.lire(entree["id_reference"])
            if texte is None:
                raise KeyError(f"Référence inconnue. Identifiants valides : {', '.join(self.references.ids())}")
            return texte
        if nom == "consulter_dip":
            return json.dumps(self.dip.consulter(entree["id_demande"]), ensure_ascii=False)
        if nom == "rechercher_demandes_similaires":
            termes = [t.lower() for t in entree["requete"].split() if len(t) > 3]
            similaires = [h for h in self.sharepoint.historique()
                          if any(t in json.dumps(h, ensure_ascii=False).lower() for t in termes)]
            return json.dumps(similaires[:5] or {"message": "Aucune demande similaire."}, ensure_ascii=False)
        if nom == OUTIL_SOUMISSION:
            return "Analyse reçue. Elle sera enregistrée dans SharePoint et soumise aux règles d'escalade."
        raise KeyError(nom)
