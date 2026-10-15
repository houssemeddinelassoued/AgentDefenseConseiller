"""Règles d'escalade vers un humain (niveau d'autonomie L3 avancé / L4 supervisé)."""

from __future__ import annotations

from .config import Config
from .modeles import Resultat


def appliquer_escalade(resultats: list[Resultat], config: Config) -> list[Resultat]:
    """Classe les dossiers par priorité et marque ceux qui exigent une validation humaine.

    - Top N des recommandations (cas stratégiques) ;
    - confiance sous le seuil ;
    - voie « Revue humaine approfondie » (ambiguïté reconnue par l'agent) ;
    - contradictions détectées ;
    - au moins un risque de niveau élevé ;
    - toute erreur, refus ou dossier hors périmètre de classification.
    """
    analyses = sorted((r for r in resultats if r.analyse), key=lambda r: r.analyse.priorite, reverse=True)
    for rang, r in enumerate(analyses, start=1):
        r.rang_priorite = rang

    for r in resultats:
        motifs: list[str] = []
        if r.analyse is None:
            motifs.append(r.erreur or "Analyse indisponible")
        else:
            a = r.analyse
            if r.rang_priorite and r.rang_priorite <= config.top_n_validation:
                motifs.append(f"Top {config.top_n_validation} des recommandations (cas stratégique)")
            if a.confiance < config.seuil_confiance:
                motifs.append(f"Faible confiance ({a.confiance:.2f} < {config.seuil_confiance:.2f})")
            if a.voie_recommandee == "Revue humaine approfondie":
                motifs.append("Dossier ambigu : revue humaine recommandée par l'agent")
            if a.contradictions:
                motifs.append(f"Contradictions détectées ({len(a.contradictions)})")
            if any(x.niveau == "élevé" for x in a.risques):
                motifs.append("Risque de niveau élevé")
        if r.integrite_ok is False:
            motifs.append("ALERTE : la demande originale a été modifiée pendant le traitement")
        r.motifs_escalade = motifs
        r.escalade = bool(motifs)
    return resultats
