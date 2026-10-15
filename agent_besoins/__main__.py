"""Point d'entrée : `python -m agent_besoins analyser|demo [options]`."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

from .config import RACINE, Config
from .moteurs import ClientOllama, MoteurIndisponible, libelle_moteur
from .pipeline import ErreurFatale, executer_analyse, executer_demo, titres_references
from .rapport import exporter_pdf, generer_rapport


def _afficher(rang: int, total: int, demande, resultat, secondes: float) -> None:
    if resultat is None:
        print(f"[{rang}/{total}] {demande.id} — {demande.titre}", flush=True)
    else:
        etat = resultat.analyse.voie_recommandee if resultat.analyse else f"non analysé ({resultat.erreur})"
        print(f"      → {etat} [{secondes:.0f} s]", flush=True)


def main() -> None:
    # Console Windows (cp1252) : forcer l'UTF-8 pour les accents et symboles de progression.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(prog="agent_besoins", description="Agent « Analyse des Besoins en Innovation » (RDDC)")
    p.add_argument("mode", choices=["analyser", "demo", "modeles-ollama"],
                   help="analyser : analyse réelle par le modèle ; demo : analyses pré-calculées ; "
                        "modeles-ollama : lister les modèles Ollama installés")
    p.add_argument("--fournisseur", choices=["anthropic", "ollama"], help="Moteur : Claude (API) ou Ollama (local)")
    p.add_argument("--modele-ollama", help="Modèle Ollama à utiliser (défaut : gemma4:latest)")
    p.add_argument("--ollama-url", help="Adresse du serveur Ollama (défaut : http://localhost:11434)")
    p.add_argument("--limite", type=int, help="N'analyser que les N premières demandes (essais)")
    p.add_argument("--top-n", type=int, help="Nombre de recommandations prioritaires soumises à validation (défaut 20)")
    p.add_argument("--sortie", type=Path, default=RACINE / "sortie", help="Dossier du rapport")
    p.add_argument("--pdf", action="store_true", help="Exporter aussi le rapport en PDF (Edge/Chrome requis)")
    p.add_argument("--exemples", type=Path, default=RACINE / "exemples" / "analyses_demo.json")
    args = p.parse_args()

    config = Config()
    if args.top_n is not None:
        config = replace(config, top_n_validation=args.top_n)
    if args.fournisseur:
        config = replace(config, fournisseur=args.fournisseur)
    if args.modele_ollama:
        config = replace(config, ollama_modele=args.modele_ollama)
    if args.ollama_url:
        config = replace(config, ollama_url=args.ollama_url)

    if args.mode == "modeles-ollama":
        try:
            modeles = ClientOllama(config.ollama_url, 10).modeles()
        except MoteurIndisponible as exc:
            sys.exit(str(exc))
        for nom, capacites in modeles.items():
            note = "outils ✓" if "tools" in capacites else "sans outils (contexte pré-chargé + sortie JSON)"
            print(f"  {nom:30} {note}")
        return

    if args.mode == "analyser":
        print(f"Moteur : {libelle_moteur(config)}", flush=True)
        try:
            resultats = executer_analyse(config, args.limite, progression=_afficher)
        except (MoteurIndisponible, ErreurFatale) as exc:
            sys.exit(str(exc))
    else:
        resultats = executer_demo(config, args.exemples)

    html = generer_rapport(resultats, config, args.sortie / "rapport_analyse_besoins.html", titres_references(config),
                           mode_demo=args.mode == "demo", moteur=libelle_moteur(config))
    (args.sortie / "resultats.json").write_text(
        json.dumps([r.model_dump() for r in resultats], ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Rapport HTML : {html}")
    if args.pdf:
        pdf = exporter_pdf(html, html.with_suffix(".pdf"))
        print(f"Rapport PDF  : {pdf}" if pdf else "PDF non généré : Edge ou Chrome introuvable (utilisez le bouton Imprimer).")


if __name__ == "__main__":
    main()
