# Agent « Analyse des Besoins en Innovation » — Programme RDDC

Prototype d'agent d'IA qui analyse les besoins en soutien S&T des Forces armées canadiennes et
recommande la voie d'approvisionnement : **R&D interne (RDDC)**, **défi d'innovation IDEaS** ou
**revue humaine approfondie**. Il produit un **rapport HTML imprimable en PDF**.

## Démarrage rapide

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt

# Démonstration (aucun appel API) : analyses pré-calculées sur des demandes fictives
.venv\Scripts\python -m agent_besoins demo --top-n 3 --pdf

# Analyse réelle avec Claude (requiert ANTHROPIC_API_KEY)
set ANTHROPIC_API_KEY=...
.venv\Scripts\python -m agent_besoins analyser --pdf
```

### Modèle local avec Ollama (aucune donnée ne quitte le poste)

```bash
ollama serve                                   # si le service n'est pas déjà lancé
.venv\Scripts\python -m agent_besoins modeles-ollama          # modèles installés et prise en charge des outils
.venv\Scripts\python -m agent_besoins analyser --fournisseur ollama --pdf
.venv\Scripts\python -m agent_besoins analyser --fournisseur ollama --modele-ollama llama3.2:latest --limite 2
```

Variables d'environnement équivalentes : `AGENT_FOURNISSEUR=ollama`, `OLLAMA_MODELE`, `OLLAMA_HOST`,
`OLLAMA_NUM_CTX` (contexte, 32 768 par défaut). Modèle par défaut : `gemma4:latest`.

- **Modèle avec outils** (`tools` dans `ollama show`) : même boucle agentique que Claude.
- **Modèle sans outils** : les références, les données DIP et l'historique sont chargés d'avance
  (et journalisés), puis l'analyse est demandée en JSON contraint par schéma.
- Dans les deux cas, si le modèle ne soumet pas d'analyse valide, l'agent la redemande en JSON
  contraint, avec une seconde tentative qui renvoie l'erreur au modèle. Sinon, le dossier est escaladé.
- Les garde-fous (outils autorisés, classification, intégrité, écriture confinée) sont identiques.
  Exécuter le modèle en local ne lève **pas** le filtre de classification.
- Un modèle local de 8 milliards de paramètres est plus lent (1 à 4 min par dossier ici) et moins
  fiable que Claude : comparez-le aux décisions des experts avant de lui confier des dossiers réels.

### Application web (Streamlit)

```bash
.venv\Scripts\streamlit run streamlit_app.py
```

Tableau de bord des indicateurs, priorisation, file de validation humaine, fiches par dossier,
traçabilité et téléchargement du rapport HTML imprimable. Le moteur se choisit dans la barre
latérale : démonstration, Claude (API) ou Ollama (local). Le Top N et le seuil de confiance
s'appliquent sans relancer l'analyse.

**Déploiement sur Streamlit Community Cloud** : sur [share.streamlit.io](https://share.streamlit.io),
« Create app » → dépôt `houssemeddinelassoued/AgentDefenseConseiller`, branche `main`, fichier
`streamlit_app.py`. Pour activer Claude, ajoutez dans *Settings → Secrets* :

```toml
ANTHROPIC_API_KEY = "sk-ant-..."
```

Sans secret, l'application publique reste en mode démonstration. Avec une clé, restreignez
l'accès à l'application (*Settings → Sharing*), sinon tout visiteur peut lancer des analyses
facturées sur votre compte. Ollama n'est pas joignable depuis le cloud (`localhost` y désigne le
serveur Streamlit) : utilisez-le avec l'application lancée en local.

Sorties dans `sortie/` : `rapport_analyse_besoins.html` (bouton « Imprimer / Exporter en PDF »),
`rapport_analyse_besoins.pdf` (option `--pdf`, via Edge ou Chrome sans tête) et `resultats.json`.
En mode `analyser`, chaque analyse est aussi déposée dans `donnees/sharepoint/analyses/`.

## Correspondance avec la carte d'identité

| Carte d'identité | Mise en œuvre |
|---|---|
| Objectif : recommander la voie | `prompts.py` (critères), outil `soumettre_analyse` à schéma strict |
| Données : demande, contexte, références, historique | `connecteurs.py` : SharePoint, ERP DIP, références autorisées, historique |
| Outils | Lecture : `rechercher_references`, `lire_reference`, `consulter_dip`, `rechercher_demandes_similaires` |
| Actions permises | Lire, analyser, recommander, signaler les risques, prioriser, enregistrer dans SharePoint |
| Actions interdites | Impossibles par construction : aucun outil de suppression, de modification, d'envoi ou de lancement ; tout outil inconnu est refusé et journalisé ; écriture confinée à la bibliothèque d'analyses, sans écrasement ; empreinte SHA-256 des demandes vérifiée avant et après |
| Escalade | `escalade.py` : Top 20, confiance < 0,70, voie « revue humaine », contradictions, risque élevé, erreur |
| Autonomie L3 / L4 | Les dossiers non escaladés sont traités en autonomie ; les autres vont dans la file de validation du rapport |
| Mesures de succès | Section 6 du rapport, à compléter par les experts à partir de la colonne « Décision » |
| Traçabilité | Journal horodaté de chaque appel d'outil, références citées, consommation de jetons |

Garde-fou supplémentaire : un dossier dont la classification dépasse `NON CLASSIFIÉ / PROTÉGÉ A`
(paramètre `classifications_autorisees` dans `config.py`) **n'est jamais transmis au modèle** ; il
est orienté directement vers un analyste habilité.

## Architecture

```
agent_besoins/
  config.py       paramètres (modèle, seuils, chemins, classifications autorisées)
  modeles.py      schémas Pydantic : Demande, Analyse, Resultat, Trace
  connecteurs.py  SharePoint / ERP DIP / références (simulés par fichiers locaux)
  outils.py       outils exposés au modèle + exécuteur appliquant la politique d'actions
  prompts.py      consignes système (mises en cache entre les demandes)
  moteurs.py      moteurs interchangeables : Claude (API Anthropic) ou Ollama (local, API REST)
  agent.py        boucle agentique par demande, indépendante du moteur
  escalade.py     règles de validation humaine
  rapport.py      rapport HTML imprimable + export PDF
donnees/          jeu de données FICTIF (demandes, références, DIP, historique)
exemples/         analyses pré-calculées pour le mode démonstration
```

Paramètres de l'appel Claude : `claude-opus-5-5`, `effort: high`, mise en cache des consignes et des
outils (utile pour ~1 000 demandes par an) et repli côté serveur (`fallbacks: "default"`) si un
classifieur de sécurité décline une requête ; un refus restant est escaladé.

## Passage en production — points à traiter

- **Connecteurs** : remplacer les classes de `connecteurs.py` par Microsoft Graph (SharePoint),
  l'API de l'outil DIP et le corpus de références officiel, en gardant la même interface.
  Teams, Outlook, le navigateur et les autres API internes de la carte d'identité ne sont **pas
  encore branchés** : prévoir Outlook/SharePoint comme déclencheurs (nouvelle requête) et
  Teams pour notifier les validateurs, sans y transmettre le contenu des analyses.
- **Sécurité de l'information** : faire approuver l'hébergement du modèle (point de terminaison et
  région) pour le niveau d'information traité, selon les politiques du Ministère.
- **Références** : les fichiers de `donnees/references/` sont illustratifs ; les remplacer par les
  documents autorisés.
- **Évaluation** : mesurer la pertinence sur un échantillon de dossiers déjà tranchés par les
  experts avant d'élargir l'autonomie.
