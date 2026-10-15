"""Génération du rapport HTML (imprimable en PDF) et export PDF par navigateur sans tête."""

from __future__ import annotations

import re
import shutil
import subprocess
from collections import Counter
from datetime import datetime
from html import escape
from pathlib import Path

from .config import Config
from .modeles import Resultat

VOIES = {
    "R&D interne (RDDC)": ("rd", "R&D interne"),
    "Défi d'innovation IDEaS": ("ideas", "Défi IDEaS"),
    "Revue humaine approfondie": ("revue", "Revue humaine"),
}


def e(texte) -> str:
    return escape(str(texte), quote=True)


def _liste(items: list[str], vide: str = "Aucun élément signalé.") -> str:
    if not items:
        return f'<p class="vide">{e(vide)}</p>'
    return "<ul>" + "".join(f"<li>{e(i)}</li>" for i in items) + "</ul>"


def _badge_voie(voie: str) -> str:
    cle, court = VOIES.get(voie, ("revue", voie))
    return f'<span class="badge voie-{cle}">{e(court)}</span>'


def _badge_statut(r: Resultat) -> str:
    if r.escalade:
        return '<span class="badge statut-humain">Validation humaine</span>'
    return '<span class="badge statut-auto">Autonome (L3)</span>'


def _jauge(valeur: float, classe: str) -> str:
    return f'<span class="jauge"><span class="jauge-rempli {classe}" style="width:{max(0, min(100, valeur)):.0f}%"></span></span>'


# --------------------------------------------------------------------------- sections

def _synthese(resultats: list[Resultat], config: Config) -> str:
    analyses = [r.analyse for r in resultats if r.analyse]
    voies = Counter(a.voie_recommandee for a in analyses)
    n_escalade = sum(r.escalade for r in resultats)
    n_hors = sum(1 for r in resultats if r.analyse is None)
    confiance = sum(a.confiance for a in analyses) / len(analyses) if analyses else 0
    total = len(resultats)

    tuiles = [
        ("Demandes reçues", total, "dans ce lot"),
        ("Analysées par l'agent", len(analyses), f"{n_hors} non transmise(s) au modèle"),
        ("Validation humaine", n_escalade, f"{(n_escalade / total * 100 if total else 0):.0f} % du lot"),
        ("Confiance moyenne", f"{confiance:.2f}", f"seuil d'escalade : {config.seuil_confiance:.2f}"),
    ]
    html_tuiles = "".join(
        f'<div class="tuile"><div class="tuile-lib">{e(l)}</div><div class="tuile-val">{e(v)}</div>'
        f'<div class="tuile-sous">{e(s)}</div></div>' for l, v, s in tuiles
    )

    barres = ""
    for voie, (cle, court) in VOIES.items():
        n = voies.get(voie, 0)
        pct = n / len(analyses) * 100 if analyses else 0
        barres += (
            f'<div class="repart-ligne"><span class="repart-lib">{e(court)}</span>'
            f'<span class="repart-barre"><span class="repart-rempli voie-{cle}-bg" style="width:{pct:.0f}%"></span></span>'
            f'<span class="repart-n">{n}</span></div>'
        )

    motifs = Counter(re.split(r" \(| :", m)[0] for r in resultats for m in r.motifs_escalade)
    lignes_motifs = "".join(f"<tr><td>{e(m)}</td><td class='num'>{n}</td></tr>" for m, n in motifs.most_common())

    return f"""
<section id="synthese">
  <h2><span class="num-sec">1</span>Synthèse</h2>
  <div class="tuiles">{html_tuiles}</div>
  <div class="deux-col">
    <div class="carte">
      <h3>Répartition des voies recommandées</h3>
      {barres}
    </div>
    <div class="carte">
      <h3>Motifs de validation humaine</h3>
      <table class="compact"><thead><tr><th>Motif</th><th class="num">Dossiers</th></tr></thead>
      <tbody>{lignes_motifs or "<tr><td colspan=2>Aucun</td></tr>"}</tbody></table>
      <p class="note">Un dossier peut cumuler plusieurs motifs.</p>
    </div>
  </div>
</section>"""


def _priorisation(resultats: list[Resultat]) -> str:
    ordonnes = sorted(resultats, key=lambda r: (r.rang_priorite is None, r.rang_priorite or 0))
    lignes = ""
    for r in ordonnes:
        a = r.analyse
        if a:
            lignes += (
                f"<tr><td class='num'>{r.rang_priorite}</td>"
                f"<td><a href='#fiche-{e(r.demande_id)}'>{e(r.demande_id)}</a></td>"
                f"<td>{e(r.titre)}</td><td>{_badge_voie(a.voie_recommandee)}</td>"
                f"<td class='num'>{a.priorite}</td><td class='num'>{a.confiance:.2f}</td>"
                f"<td>{_badge_statut(r)}</td></tr>"
            )
        else:
            lignes += (
                f"<tr><td class='num'>—</td><td><a href='#fiche-{e(r.demande_id)}'>{e(r.demande_id)}</a></td>"
                f"<td>{e(r.titre)}</td><td><span class='badge voie-bloque'>Non analysé</span></td>"
                f"<td class='num'>—</td><td class='num'>—</td><td>{_badge_statut(r)}</td></tr>"
            )
    return f"""
<section id="priorisation">
  <h2><span class="num-sec">2</span>Tableau de priorisation</h2>
  <table>
    <thead><tr><th class="num">Rang</th><th>Dossier</th><th style="width:36%">Besoin</th><th>Voie recommandée</th>
    <th class="num">Priorité</th><th class="num">Confiance</th><th>Statut</th></tr></thead>
    <tbody>{lignes}</tbody>
  </table>
</section>"""


def _file_humaine(resultats: list[Resultat]) -> str:
    items = ""
    for r in sorted((r for r in resultats if r.escalade), key=lambda r: (r.rang_priorite is None, r.rang_priorite or 0)):
        items += (
            f"<tr><td><a href='#fiche-{e(r.demande_id)}'>{e(r.demande_id)}</a></td><td>{e(r.titre)}</td>"
            f"<td>{_liste(r.motifs_escalade)}</td>"
            "<td class='decision'>☐ Approuvée<br>☐ Réorientée<br>☐ Info. requise</td></tr>"
        )
    return f"""
<section id="revue-humaine">
  <h2><span class="num-sec">3</span>File de validation humaine</h2>
  <p>Dossiers transférés aux responsables RDDC conformément aux règles d'escalade. La colonne
  « Décision » est prévue pour la validation sur la version imprimée.</p>
  <table>
    <thead><tr><th>Dossier</th><th style="width:30%">Besoin</th><th>Motifs</th><th>Décision</th></tr></thead>
    <tbody>{items or "<tr><td colspan=4>Aucun dossier à valider.</td></tr>"}</tbody>
  </table>
</section>"""


def _fiche(r: Resultat, references_titres: dict[str, str]) -> str:
    entete = f"""
  <div class="fiche-entete">
    <div><div class="fiche-id">{e(r.demande_id)}</div><h3>{e(r.titre)}</h3></div>
    <div class="fiche-badges">{_badge_voie(r.analyse.voie_recommandee) if r.analyse else ""}{_badge_statut(r)}</div>
  </div>
  <dl class="meta">
    <div><dt>Demandeur</dt><dd>{e(r.demandeur)}</dd></div>
    <div><dt>Reçue le</dt><dd>{e(r.date_reception)}</dd></div>
    <div><dt>Classification</dt><dd>{e(r.classification)}</dd></div>
    <div><dt>Intégrité de l'original</dt><dd>{"Vérifiée ✓" if r.integrite_ok else ("ALTÉRÉE ✗" if r.integrite_ok is False else "—")}</dd></div>
  </dl>"""

    if r.analyse is None:
        return f"""
<article class="fiche" id="fiche-{e(r.demande_id)}">{entete}
  <div class="alerte"><strong>Dossier non analysé par l'agent.</strong> {e(r.erreur or "")}</div>
</article>"""

    a = r.analyse
    criteres = "".join(
        f"<tr><td>{e(c.critere)}</td><td>{e(c.evaluation)}</td>"
        f"<td><span class='fav fav-{ {'R&D interne': 'rd', 'IDEaS': 'ideas'}.get(c.favorise, 'neutre') }'>{e(c.favorise)}</span></td></tr>"
        for c in a.criteres
    )
    risques = "".join(
        f"<tr><td>{e(x.description)}</td><td><span class='niv niv-{ {'faible': 'f', 'moyen': 'm', 'élevé': 'e'}[x.niveau] }'>{e(x.niveau)}</span></td>"
        f"<td>{e(x.mitigation)}</td></tr>" for x in a.risques
    )
    refs = _liste([f"{ref} — {references_titres.get(ref, 'référence')}" for ref in a.references_utilisees],
                  "Aucune référence citée.")
    motifs = (f'<div class="alerte"><strong>Validation humaine requise :</strong> {e(" · ".join(r.motifs_escalade))}</div>'
              if r.escalade else
              '<div class="ok">Traitement autonome (L3) : recommandation enregistrée, soumise à l\'échantillonnage qualité.</div>')

    return f"""
<article class="fiche" id="fiche-{e(r.demande_id)}">{entete}
  {motifs}
  <h4>Résumé du besoin</h4>
  <p>{e(a.resume_besoin)}</p>
  <div class="deux-col">
    <div>
      <h4>Adéquation des voies</h4>
      <div class="score"><span>R&amp;D interne (RDDC)</span>{_jauge(a.scores_voies.rd_interne, 'voie-rd-bg')}<b>{a.scores_voies.rd_interne}</b></div>
      <div class="score"><span>Défi IDEaS</span>{_jauge(a.scores_voies.ideas, 'voie-ideas-bg')}<b>{a.scores_voies.ideas}</b></div>
    </div>
    <div>
      <h4>Indicateurs</h4>
      <div class="score"><span>Priorité (rang {r.rang_priorite})</span>{_jauge(a.priorite, 'prio-bg')}<b>{a.priorite}</b></div>
      <div class="score"><span>Confiance</span>{_jauge(a.confiance * 100, 'conf-bg')}<b>{a.confiance:.2f}</b></div>
      <div class="score"><span>Maturité (TRL)</span><span class="trl">{e(a.trl_estime)}</span></div>
    </div>
  </div>
  <h4>Justification de la recommandation</h4>
  {_liste(a.justification)}
  <p class="note"><b>Priorité :</b> {e(a.justification_priorite)}</p>
  <h4>Critères d'orientation</h4>
  <table class="compact"><thead><tr><th>Critère</th><th>Évaluation</th><th>Favorise</th></tr></thead><tbody>{criteres}</tbody></table>
  <h4>Risques potentiels</h4>
  <table class="compact"><thead><tr><th>Risque</th><th>Niveau</th><th>Mitigation</th></tr></thead>
  <tbody>{risques or "<tr><td colspan=3>Aucun risque signalé.</td></tr>"}</tbody></table>
  <div class="deux-col">
    <div><h4>Zones grises</h4>{_liste(a.zones_grises)}</div>
    <div><h4>Contradictions</h4>{_liste(a.contradictions, "Aucune contradiction détectée.")}</div>
  </div>
  <h4>Questions à adresser au demandeur</h4>
  {_liste(a.questions_ouvertes)}
  <h4>Références autorisées utilisées</h4>
  {refs}
</article>"""


def _tracabilite(resultats: list[Resultat], mode_demo: bool) -> str:
    if mode_demo:
        corps = ("<p class='alerte'>Mode démonstration : les analyses de ce rapport sont des exemples "
                 "pré-calculés. Aucun appel au modèle ni aux outils n'a été effectué ; le journal des appels "
                 "d'outils est donc vide. Les vérifications d'intégrité des demandes, elles, sont réelles.</p>")
    else:
        lignes = "".join(
            f"<tr><td>{e(r.demande_id)}</td><td>{e(t.horodatage)}</td><td><code>{e(t.outil)}</code></td>"
            f"<td><code>{e(', '.join(f'{k}={v}' for k, v in t.entree.items() if k != 'justification')[:90])}</code></td>"
            f"<td><span class='trace-{e(t.statut)}'>{e(t.statut)}</span></td></tr>"
            for r in resultats for t in r.traces
        )
        corps = (f"<table class='compact trace'><thead><tr><th>Dossier</th><th>Horodatage (UTC)</th><th>Outil</th>"
                 f"<th>Paramètres</th><th>Statut</th></tr></thead><tbody>{lignes or '<tr><td colspan=5>Aucun appel.</td></tr>'}</tbody></table>")
    jetons_e = sum(r.jetons_entree for r in resultats)
    jetons_s = sum(r.jetons_sortie for r in resultats)
    integrite = "".join(
        f"<tr><td>{e(r.demande_id)}</td><td>{'Vérifiée ✓' if r.integrite_ok else 'ALTÉRÉE ✗' if r.integrite_ok is False else '—'}</td></tr>"
        for r in resultats
    )
    return f"""
<section id="tracabilite">
  <h2><span class="num-sec">5</span>Traçabilité et contrôle</h2>
  <div class="deux-col">
    <div class="carte"><h3>Intégrité des demandes originales (SHA-256)</h3>
      <table class="compact"><thead><tr><th>Dossier</th><th>Empreinte avant / après</th></tr></thead><tbody>{integrite}</tbody></table></div>
    <div class="carte"><h3>Consommation</h3>
      <p>Jetons en entrée : <b>{jetons_e:,}</b><br>Jetons en sortie : <b>{jetons_s:,}</b></p>
      <p class="note">Les analyses sont enregistrées dans la bibliothèque SharePoint prévue, sans écraser de version antérieure.</p></div>
  </div>
  <h3>Journal des appels d'outils</h3>
  {corps}
</section>"""


def _carte_identite(config: Config, moteur: str) -> str:
    return f"""
<section id="agent">
  <h2><span class="num-sec">6</span>Carte d'identité de l'agent et garde-fous appliqués</h2>
  <div class="deux-col">
    <div class="carte">
      <h3>Profil</h3>
      <dl class="meta vertical">
        <div><dt>Objectif</dt><dd>Recommander la meilleure voie d'approvisionnement S&amp;T : R&amp;D interne, défi IDEaS ou revue humaine.</dd></div>
        <div><dt>Utilisateurs</dt><dd>Responsables et analystes du programme RDDC.</dd></div>
        <div><dt>Volume ciblé</dt><dd>≈ 1 000 besoins par an (demandes de 4 à 5 pages).</dd></div>
        <div><dt>Autonomie</dt><dd>L3 avancé / L4 supervisé — validation humaine des cas stratégiques, ambigus ou à risque.</dd></div>
        <div><dt>Moteur</dt><dd>{e(moteur)}</dd></div>
      </dl>
    </div>
    <div class="carte">
      <h3>Politique d'actions</h3>
      <div class="actions">
        <div class="permises"><b>Permises</b><ul><li>Lire les demandes</li><li>Analyser le contenu</li><li>Formuler des recommandations</li>
          <li>Souligner les risques</li><li>Prioriser et justifier</li><li>Enregistrer l'analyse dans SharePoint</li></ul></div>
        <div class="interdites"><b>Interdites</b><ul><li>Effacer des données ou fichiers</li><li>Modifier la demande originale</li>
          <li>Transmettre ailleurs que dans SharePoint</li><li>Lancer un projet ou un défi sans validation</li></ul></div>
      </div>
      <p class="note">Mise en œuvre : outils en lecture seule uniquement, aucune fonction de suppression, écriture confinée
      à la bibliothèque d'analyses, contrôle d'empreinte SHA-256 des originaux, refus journalisé de tout outil non autorisé,
      dossiers au-delà de « {e(' / '.join(config.classifications_autorisees))} » jamais transmis au modèle.</p>
    </div>
  </div>
  <div class="carte">
    <h3>Mesures de succès — à compléter par les experts RDDC</h3>
    <table class="compact"><thead><tr><th>Indicateur</th><th>Méthode de mesure</th><th>Valeur</th></tr></thead><tbody>
      <tr><td>Pertinence des recommandations</td><td>% jugées pertinentes par les experts (colonne « Décision »)</td><td class="a-remplir"></td></tr>
      <tr><td>Distinction R&amp;D interne / IDEaS</td><td>% de voies confirmées sans réorientation</td><td class="a-remplir"></td></tr>
      <tr><td>Détection des zones grises</td><td>% de dossiers ambigus correctement escaladés</td><td class="a-remplir"></td></tr>
      <tr><td>Temps d'analyse initiale</td><td>Durée moyenne par dossier vs référence manuelle</td><td class="a-remplir"></td></tr>
      <tr><td>Traçabilité</td><td>% de recommandations avec références et journal complets</td><td class="a-remplir"></td></tr>
    </tbody></table>
  </div>
</section>"""


# --------------------------------------------------------------------------- document

def generer_rapport(resultats: list[Resultat], config: Config, destination: Path,
                    references_titres: dict[str, str], mode_demo: bool = False, moteur: str = "") -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(construire_html(resultats, config, references_titres, mode_demo, moteur), encoding="utf-8")
    return destination


def construire_html(resultats: list[Resultat], config: Config, references_titres: dict[str, str],
                    mode_demo: bool = False, moteur: str = "") -> str:
    maintenant = datetime.now()
    ordonnes = sorted(resultats, key=lambda r: (r.rang_priorite is None, r.rang_priorite or 0))
    fiches = "".join(_fiche(r, references_titres) for r in ordonnes)
    bandeau_demo = (
        '<div class="bandeau-demo">DÉMONSTRATION — Demandes fictives et analyses pré-calculées à titre '
        "d'illustration. Ne reflète aucun besoin réel des FAC.</div>" if mode_demo else ""
    )
    lot = f"Top N = {config.top_n_validation}"

    html = f"""<!doctype html>
<html lang="fr-CA">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Rapport d'analyse des besoins</title>
<style>{CSS}</style>
</head>
<body>
<div class="barre-outils no-print">
  <button onclick="window.print()">Imprimer / Exporter en PDF</button>
  <span>Astuce : choisissez « Enregistrer au format PDF » comme imprimante, et activez « Graphiques d'arrière-plan ».</span>
</div>
<main>
{bandeau_demo}
<header class="couverture">
  <div class="sur-titre">Ministère de la Défense nationale · Programme RDDC</div>
  <h1>Analyse des besoins en innovation</h1>
  <p class="sous-titre">Orientation des besoins en soutien S&amp;T des Forces armées canadiennes :
  R&amp;D interne, défi d'innovation IDEaS ou revue humaine</p>
  <dl class="meta">
    <div><dt>Produit le</dt><dd>{maintenant:%Y-%m-%d %H:%M}</dd></div>
    <div><dt>Dossiers</dt><dd>{len(resultats)}</dd></div>
    <div><dt>Règle d'escalade</dt><dd>{e(lot)} · confiance &lt; {config.seuil_confiance:.2f}</dd></div>
    <div><dt>Moteur</dt><dd>{e(moteur if not mode_demo else "Aucun (démonstration)")}</dd></div>
  </dl>
  <p class="avertissement">Document de travail — recommandations non engageantes produites par un agent d'IA.
  Aucune voie d'approvisionnement n'est retenue sans validation par un responsable RDDC.</p>
  <nav class="no-print"><a href="#synthese">Synthèse</a><a href="#priorisation">Priorisation</a>
  <a href="#revue-humaine">Validation humaine</a><a href="#fiches">Fiches</a><a href="#tracabilite">Traçabilité</a><a href="#agent">Agent</a></nav>
</header>
{_synthese(resultats, config)}
{_priorisation(resultats)}
{_file_humaine(resultats)}
<section id="fiches">
  <h2><span class="num-sec">4</span>Fiches d'analyse par dossier</h2>
  {fiches}
</section>
{_tracabilite(resultats, mode_demo)}
{_carte_identite(config, moteur if not mode_demo else 'Aucun (démonstration)')}
<footer>Agent « Analyse des Besoins en Innovation » · Rapport généré le {maintenant:%Y-%m-%d} · Document de travail</footer>
</main>
</body>
</html>"""
    return html


def exporter_pdf(html: Path, pdf: Path) -> Path | None:
    """Imprime le rapport en PDF avec Edge ou Chrome sans tête (si disponible)."""
    candidats = [
        shutil.which("msedge"), shutil.which("chrome"), shutil.which("google-chrome"), shutil.which("chromium"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    ]
    navigateur = next((c for c in candidats if c and Path(c).exists()), None)
    if navigateur is None:
        return None
    subprocess.run(
        [navigateur, "--headless", "--disable-gpu", "--no-pdf-header-footer",
         f"--print-to-pdf={pdf.resolve()}", html.resolve().as_uri()],
        check=True, capture_output=True, timeout=120,
    )
    return pdf if pdf.exists() else None


CSS = """
:root{
  --encre:#0f1f3a;--texte:#26334d;--doux:#5b6880;--trait:#d9e0ea;--fond:#f4f6fa;--papier:#fff;
  --marine:#0b3d91;--rd:#1d5fd1;--rd-p:#e3edfd;--ideas:#0e8a7a;--ideas-p:#dcf3ef;
  --revue:#c25e00;--revue-p:#fdecdc;--rouge:#b42318;--rouge-p:#fde8e7;--vert:#1b7f3b;--vert-p:#e3f4e8;
}
*{box-sizing:border-box}
body{margin:0;background:var(--fond);color:var(--texte);font:14px/1.5 "Segoe UI",system-ui,-apple-system,Roboto,Arial,sans-serif}
main{max-width:1040px;margin:0 auto;padding:24px 16px 48px}
h1,h2,h3,h4{color:var(--encre);line-height:1.25}
h1{font-size:32px;margin:6px 0 8px}
h2{font-size:21px;margin:36px 0 14px;padding-bottom:8px;border-bottom:2px solid var(--marine);display:flex;align-items:center;gap:10px}
h3{font-size:16px;margin:0 0 10px}
h4{font-size:13px;text-transform:uppercase;letter-spacing:.06em;color:var(--marine);margin:18px 0 6px}
a{color:var(--rd)}
.num-sec{display:inline-grid;place-items:center;width:28px;height:28px;border-radius:6px;background:var(--marine);color:#fff;font-size:14px}
.barre-outils{position:sticky;top:0;z-index:5;display:flex;gap:14px;align-items:center;flex-wrap:wrap;padding:10px 16px;background:var(--encre);color:#cfd8e6;font-size:13px}
.barre-outils button{background:#fff;color:var(--encre);border:0;border-radius:6px;padding:8px 14px;font-weight:600;cursor:pointer}
.barre-outils button:hover{background:#dbe6fb}
.bandeau-demo{background:var(--revue-p);color:#7a3b00;border:1px solid #f3c597;border-radius:8px;padding:10px 14px;font-weight:600;margin-bottom:16px}
.couverture{background:linear-gradient(135deg,#0b3d91,#1d5fd1);color:#fff;border-radius:14px;padding:28px}
.couverture h1{color:#fff}
.sur-titre{text-transform:uppercase;letter-spacing:.12em;font-size:12px;opacity:.85}
.sous-titre{font-size:16px;opacity:.95;margin:0 0 18px}
.couverture .meta dt{color:#bcd0f5}.couverture .meta dd{color:#fff}
.avertissement{font-size:12.5px;background:rgba(255,255,255,.12);border-radius:8px;padding:10px 12px;margin:16px 0 0}
nav{display:flex;flex-wrap:wrap;gap:8px;margin-top:16px}
nav a{color:#fff;text-decoration:none;background:rgba(255,255,255,.16);padding:5px 10px;border-radius:999px;font-size:12.5px}
.meta{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;margin:12px 0}
.meta dt{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--doux)}
.meta dd{margin:2px 0 0;font-weight:600;color:var(--encre)}
.meta.vertical{grid-template-columns:1fr}
.tuiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-bottom:14px}
.tuile,.carte{background:var(--papier);border:1px solid var(--trait);border-radius:10px;padding:14px 16px}
.tuile-lib{font-size:12px;color:var(--doux);text-transform:uppercase;letter-spacing:.05em}
.tuile-val{font-size:30px;font-weight:700;color:var(--encre);font-variant-numeric:tabular-nums}
.tuile-sous{font-size:12px;color:var(--doux)}
.deux-col{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px;margin-bottom:6px}
.repart-ligne{display:grid;grid-template-columns:110px 1fr 30px;align-items:center;gap:10px;margin:10px 0}
.repart-barre,.jauge{display:block;height:10px;background:#e8edf4;border-radius:999px;overflow:hidden}
.repart-rempli,.jauge-rempli{display:block;height:100%;border-radius:999px}
.repart-n{text-align:right;font-weight:700;font-variant-numeric:tabular-nums}
.voie-rd-bg{background:var(--rd)}.voie-ideas-bg{background:var(--ideas)}.voie-revue-bg{background:var(--revue)}
.prio-bg{background:var(--marine)}.conf-bg{background:#6b7fa3}
table{width:100%;border-collapse:collapse;background:var(--papier);border:1px solid var(--trait);border-radius:10px;overflow:hidden;font-size:13px}
th{background:#eef2f8;color:var(--encre);text-align:left;font-size:11.5px;text-transform:uppercase;letter-spacing:.04em;padding:8px 10px}
td{padding:8px 10px;border-top:1px solid var(--trait);vertical-align:top}
td a,.id{white-space:nowrap}
td ul{margin:0;padding-left:16px}
.num{text-align:right;font-variant-numeric:tabular-nums}
table.compact td,table.compact th{padding:6px 8px}
.badge{display:inline-block;font-size:11.5px;font-weight:600;padding:3px 9px;border-radius:999px;white-space:nowrap;margin:1px 4px 1px 0}
.voie-rd{background:var(--rd-p);color:var(--rd)}.voie-ideas{background:var(--ideas-p);color:var(--ideas)}
.voie-revue{background:var(--revue-p);color:var(--revue)}.voie-bloque{background:#eceff3;color:var(--doux)}
.statut-humain{background:var(--rouge-p);color:var(--rouge)}.statut-auto{background:var(--vert-p);color:var(--vert)}
.fav{font-size:11.5px;font-weight:600}.fav-rd{color:var(--rd)}.fav-ideas{color:var(--ideas)}.fav-neutre{color:var(--doux)}
.niv{font-size:11.5px;font-weight:700;padding:2px 8px;border-radius:999px}
.niv-f{background:var(--vert-p);color:var(--vert)}.niv-m{background:var(--revue-p);color:var(--revue)}.niv-e{background:var(--rouge-p);color:var(--rouge)}
.decision{white-space:nowrap;font-size:12.5px;line-height:1.8}
.fiche{background:var(--papier);border:1px solid var(--trait);border-radius:12px;padding:20px 22px;margin:0 0 20px}
.fiche-entete{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;align-items:flex-start}
.fiche-entete h3{font-size:19px;margin:2px 0 0}
.fiche-id{font-size:12px;font-weight:700;color:var(--marine);letter-spacing:.05em}
.fiche .meta{border-top:1px solid var(--trait);border-bottom:1px solid var(--trait);padding:10px 0}
.score{display:grid;grid-template-columns:170px 1fr 40px;align-items:center;gap:10px;margin:8px 0;font-size:13px}
.score b{text-align:right;font-variant-numeric:tabular-nums}
.trl{grid-column:span 2;font-weight:600;color:var(--encre)}
.alerte{background:var(--rouge-p);border-left:4px solid var(--rouge);padding:9px 12px;border-radius:6px;font-size:13px;margin:12px 0}
.ok{background:var(--vert-p);border-left:4px solid var(--vert);padding:9px 12px;border-radius:6px;font-size:13px;margin:12px 0}
.note{font-size:12.5px;color:var(--doux)}
.vide{color:var(--doux);font-style:italic;margin:4px 0}
.actions{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.permises{background:var(--vert-p);border-radius:8px;padding:10px}.interdites{background:var(--rouge-p);border-radius:8px;padding:10px}
.permises b{color:var(--vert)}.interdites b{color:var(--rouge)}
.actions ul{margin:6px 0 0;padding-left:18px;font-size:12.5px}
.a-remplir{min-width:90px;border-bottom:1px dotted var(--doux)}
.trace code{font-size:11.5px}.trace-ok{color:var(--vert);font-weight:600}.trace-erreur,.trace-refusé{color:var(--rouge);font-weight:600}
footer{margin-top:40px;padding-top:12px;border-top:1px solid var(--trait);font-size:12px;color:var(--doux);text-align:center}
@media (max-width:640px){
  .score{grid-template-columns:120px 1fr 34px}.actions{grid-template-columns:1fr}
  table{display:block;overflow-x:auto}h1{font-size:26px}
}
@page{size:letter;margin:16mm 14mm 18mm;
  @bottom-left{content:"Analyse des besoins en innovation — Document de travail";font:9px "Segoe UI",sans-serif;color:#5b6880}
  @bottom-right{content:"Page " counter(page) " / " counter(pages);font:9px "Segoe UI",sans-serif;color:#5b6880}}
@media print{
  *{-webkit-print-color-adjust:exact;print-color-adjust:exact}
  body{background:#fff;font-size:11.5px}
  main{max-width:none;padding:0}
  .no-print{display:none!important}
  .couverture{border-radius:8px;padding:18px 24px}
  .couverture h1{font-size:25px;margin:4px 0}
  .sous-titre{font-size:13px;margin-bottom:8px}
  .avertissement{margin-top:8px;padding:7px 10px}
  .tuile-val{font-size:24px}
  table{font-size:10.5px}
  th{font-size:9px}
  td,th{padding:6px 7px}
  .badge{font-size:9.5px;padding:2px 7px}
  h2{margin:22px 0 10px}
  .tuiles{grid-template-columns:repeat(4,1fr)}
  .deux-col{grid-template-columns:1fr 1fr}
  h2,h3,h4{break-after:avoid}
  #fiches{break-before:page}
  .fiche{break-inside:auto;break-before:page;border:none;padding:0;margin:0}
  .fiche:first-of-type{break-before:auto}
  tr,.carte,.tuile,.score{break-inside:avoid}
  #tracabilite,#agent{break-before:page}
  a{color:inherit;text-decoration:none}
}
"""
