"""Connecteurs vers les sources de l'agent.

Le prototype simule SharePoint, l'ERP (outil DIP) et le corpus de références avec des
fichiers locaux. En production, chaque classe est remplacée par une implémentation
Microsoft Graph / API interne exposant **la même interface** : les garde-fous restent
valables puisqu'aucune méthode de suppression ou de modification n'existe.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

from .config import Config
from .modeles import Demande


def empreinte(chemin: Path) -> str:
    return hashlib.sha256(chemin.read_bytes()).hexdigest()


class SharePoint:
    """Lecture des demandes ; écriture limitée à la bibliothèque d'analyses prévue."""

    def __init__(self, config: Config):
        self.config = config

    def lister_demandes(self) -> list[Path]:
        return sorted(self.config.dossier_demandes.glob("*.json"))

    def lire_demande(self, chemin: Path) -> Demande:
        donnees = json.loads(chemin.read_text(encoding="utf-8"))
        return Demande(**donnees, empreinte_sha256=empreinte(chemin))

    def verifier_integrite(self, chemin: Path, empreinte_initiale: str) -> bool:
        """La demande originale ne doit jamais être modifiée par l'agent."""
        return empreinte(chemin) == empreinte_initiale

    def historique(self) -> list[dict]:
        if not self.config.fichier_historique.exists():
            return []
        return json.loads(self.config.fichier_historique.read_text(encoding="utf-8"))

    def enregistrer_analyse(self, nom_fichier: str, contenu: str) -> Path:
        """Seule action d'écriture permise : déposer l'analyse dans la bibliothèque prévue."""
        destination = (self.config.bibliotheque_analyses / nom_fichier).resolve()
        bibliotheque = self.config.bibliotheque_analyses.resolve()
        if bibliotheque not in destination.parents:
            raise PermissionError(f"Écriture hors de la bibliothèque SharePoint prévue : {destination}")
        if destination.exists():
            # On n'écrase jamais : une nouvelle version horodatée est créée.
            horodatage = datetime.now().strftime("%Y%m%d-%H%M%S")
            destination = destination.with_name(f"{destination.stem}_{horodatage}{destination.suffix}")
        bibliotheque.mkdir(parents=True, exist_ok=True)
        destination.write_text(contenu, encoding="utf-8")
        return destination


class ERPDip:
    """Accès en lecture seule à l'outil DIP (projets connexes, budgets, jalons)."""

    def __init__(self, config: Config):
        self._donnees = (
            json.loads(config.fichier_dip.read_text(encoding="utf-8")) if config.fichier_dip.exists() else {}
        )

    def consulter(self, id_demande: str) -> dict:
        return self._donnees.get(id_demande, {"message": "Aucune donnée DIP liée à ce dossier."})


class References:
    """Corpus de références autorisées (fichiers Markdown, l'identifiant est le nom du fichier)."""

    def __init__(self, config: Config):
        self._docs = {
            p.stem: p.read_text(encoding="utf-8") for p in sorted(config.dossier_references.glob("*.md"))
        }

    def ids(self) -> list[str]:
        return list(self._docs)

    def titre(self, id_ref: str) -> str:
        premiere = self._docs.get(id_ref, "").splitlines()[:1]
        return premiere[0].lstrip("# ").strip() if premiere else id_ref

    def lire(self, id_ref: str) -> str | None:
        return self._docs.get(id_ref)

    def rechercher(self, requete: str, limite: int = 5) -> list[dict]:
        termes = [t for t in re.findall(r"\w{4,}", requete.lower())]
        resultats = []
        for id_ref, texte in self._docs.items():
            bas = texte.lower()
            score = sum(bas.count(t) for t in termes)
            if score:
                paragraphes = [p for p in texte.split("\n\n") if any(t in p.lower() for t in termes)]
                resultats.append({"id": id_ref, "titre": self.titre(id_ref), "score": score,
                                  "extraits": paragraphes[:3]})
        return sorted(resultats, key=lambda r: r["score"], reverse=True)[:limite]
