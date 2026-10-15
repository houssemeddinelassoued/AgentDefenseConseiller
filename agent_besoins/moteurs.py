"""Moteurs de langage interchangeables : Claude (API Anthropic) ou Ollama (modèle local).

Chaque moteur gère sa propre conversation et expose la même interface à la boucle
agentique (`agent.py`), qui reste ainsi indépendante du fournisseur.
"""

from __future__ import annotations

import base64
import http.client
import json
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field, replace

from .config import Config
from .outils import OUTIL_SOUMISSION, OUTILS
from .prompts import SYSTEME


@dataclass
class Appel:
    id: str
    nom: str
    entree: dict


@dataclass
class Tour:
    appels: list[Appel] = field(default_factory=list)
    arret: str = "fin"  # "outils" | "fin" | "refus" | "tronque"
    detail: str = ""
    jetons_entree: int = 0
    jetons_sortie: int = 0


class MoteurIndisponible(RuntimeError):
    """Le moteur ne peut pas être joint ou n'est pas configuré."""


# --------------------------------------------------------------------------- Claude

class ConversationClaude:
    def __init__(self, config: Config, client):
        self.config = config
        self.client = client
        self.messages: list = []

    @property
    def utilise_outils(self) -> bool:
        return True

    def ajouter_utilisateur(self, texte: str) -> None:
        self.messages.append({"role": "user", "content": texte})

    def tour(self) -> Tour:
        reponse = self.client.beta.messages.create(
            model=self.config.modele,
            max_tokens=self.config.max_tokens,
            output_config={"effort": self.config.effort},
            # Repli côté serveur si un classifieur de sécurité refuse la requête
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            cache_control={"type": "ephemeral"},  # consignes + outils réutilisés pour ~1000 demandes/an
            system=SYSTEME,
            tools=OUTILS,
            messages=self.messages,
        )
        t = Tour(jetons_entree=reponse.usage.input_tokens + (reponse.usage.cache_read_input_tokens or 0),
                 jetons_sortie=reponse.usage.output_tokens)
        if reponse.stop_reason == "refusal":
            categorie = reponse.stop_details.category if reponse.stop_details else None
            t.arret, t.detail = "refus", f"Requête déclinée par le modèle (catégorie : {categorie})."
            return t
        if reponse.stop_reason == "max_tokens":
            t.arret, t.detail = "tronque", "Réponse tronquée (limite de jetons atteinte)."
            return t
        # Le contenu est renvoyé tel quel (blocs de raisonnement inclus).
        self.messages.append({"role": "assistant", "content": reponse.content})
        t.appels = [Appel(b.id, b.name, b.input) for b in reponse.content if b.type == "tool_use"]
        t.arret = "outils" if t.appels else "fin"
        return t

    def ajouter_resultats(self, resultats: list[tuple[Appel, str, bool]]) -> None:
        self.messages.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": a.id, "content": c, "is_error": err}
            for a, c, err in resultats
        ]})

    def forcer_analyse(self) -> tuple[dict | None, Tour]:
        return None, Tour()


def moteur_claude(config: Config):
    import anthropic

    client = anthropic.Anthropic()
    return lambda: ConversationClaude(config, client)


# --------------------------------------------------------------------------- Ollama

SCHEMA_ANALYSE = next(o["input_schema"] for o in OUTILS if o["name"] == OUTIL_SOUMISSION)


def _borner(schema: dict) -> dict:
    """Copie du schéma avec bornes numériques : la grammaire d'Ollama contraint alors les valeurs."""
    s = json.loads(json.dumps(schema))
    for cle in ("rd_interne", "ideas"):
        s["properties"]["scores_voies"]["properties"][cle].update(minimum=0, maximum=100)
    s["properties"]["priorite"].update(minimum=0, maximum=100)
    s["properties"]["confiance"].update(minimum=0, maximum=1)
    return s


SCHEMA_ANALYSE_BORNE = _borner(SCHEMA_ANALYSE)
OUTILS_OLLAMA = [
    {"type": "function", "function": {"name": o["name"], "description": o["description"],
                                      "parameters": o["input_schema"]}}
    for o in OUTILS
]

CONSIGNE_JSON = (
    "Produisez maintenant l'analyse finale de cette demande, en français, sous la forme d'un "
    "objet JSON conforme au schéma imposé. Scores et priorité : entiers de 0 à 100 ; "
    "confiance : nombre de 0.0 à 1.0."
)


def _separer_identifiants(url: str) -> tuple[str, str | None]:
    """Retire « utilisateur:motdepasse@ » de l'adresse ; retourne (adresse sans secret, en-tête Basic)."""
    url = url.strip().rstrip("/")
    parties = urllib.parse.urlsplit(url if "://" in url else f"http://{url}")
    if parties.username is None:
        return urllib.parse.urlunsplit(parties), None
    hote = parties.hostname + (f":{parties.port}" if parties.port else "")
    jeton = f"{urllib.parse.unquote(parties.username)}:{urllib.parse.unquote(parties.password or '')}"
    entete = "Basic " + base64.b64encode(jeton.encode("utf-8")).decode("ascii")
    return urllib.parse.urlunsplit(parties._replace(netloc=hote)), entete


def masquer_identifiants(url: str) -> str:
    """Adresse affichable : le mot de passe éventuel n'apparaît jamais à l'écran ni dans le rapport."""
    propre, entete = _separer_identifiants(url)
    return f"{propre} (authentifié)" if entete else propre


def normaliser_modele(nom: str) -> str:
    return nom if ":" in nom else f"{nom}:latest"


def est_adresse_locale(url: str) -> bool:
    hote = urllib.parse.urlsplit(url if "://" in url else f"http://{url}").hostname or ""
    return hote in ("localhost", "127.0.0.1", "::1", "0.0.0.0")


def _conseil(url: str, exc: Exception) -> str:
    if est_adresse_locale(url):
        return ("Démarrez Ollama sur cette machine (« ollama serve »). Si l'application est hébergée "
                "(Streamlit Cloud), « localhost » désigne le serveur d'hébergement et non votre poste.")
    return f"Vérifiez l'adresse, le tunnel ou le pare-feu ({getattr(exc, 'reason', exc)})."


class ClientOllama:
    """Client minimal de l'API REST d'Ollama (bibliothèque standard uniquement)."""

    def __init__(self, url: str, timeout: float, api_key: str = ""):
        self.url, basic = _separer_identifiants(url)  # self.url ne contient jamais le mot de passe
        self.timeout = timeout
        # « ngrok-skip-browser-warning » évite la page d'avertissement des tunnels ngrok gratuits.
        self.entetes = {"Content-Type": "application/json", "ngrok-skip-browser-warning": "1"}
        if basic:
            self.entetes["Authorization"] = basic  # mot de passe du tunnel (politique ngrok)
        elif api_key:
            self.entetes["Authorization"] = f"Bearer {api_key}"

    def _requete(self, chemin: str, corps: dict | None = None) -> dict:
        donnees = json.dumps(corps).encode("utf-8") if corps is not None else None
        req = urllib.request.Request(f"{self.url}{chemin}", data=donnees, headers=self.entetes)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as rep:
                return json.loads(rep.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                raise MoteurIndisponible(
                    f"Accès refusé par {self.url} (401) : identifiants du tunnel ou clé API incorrects.")
            if exc.code == 403:
                raise MoteurIndisponible(
                    f"Accès refusé par {self.url} (403). Derrière un tunnel, Ollama exige l'en-tête d'hôte "
                    "localhost : lancez ngrok avec --host-header=\"localhost:11434\". Sinon, vérifiez la clé API.")
            if exc.code in (502, 503, 504) or "ngrok" in (exc.headers.get("Server") or "").lower():
                raise MoteurIndisponible(
                    f"Le tunnel {self.url} répond ({exc.code}) mais n'atteint pas Ollama : vérifiez que le poste "
                    "est allumé, qu'Ollama tourne (« ollama serve ») et que la commande ngrok est lancée.")
            raise MoteurIndisponible(f"Ollama a répondu {exc.code} : {exc.read().decode('utf-8', 'replace')[:300]}")
        except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.HTTPException) as exc:
            raise MoteurIndisponible(f"Aucun serveur Ollama ne répond à {self.url}. {_conseil(self.url, exc)}")
        except json.JSONDecodeError:
            raise MoteurIndisponible(f"{self.url} a répondu, mais ce n'est pas l'API Ollama (vérifiez l'adresse).")

    def modeles(self) -> dict[str, list[str] | None]:
        """Nom du modèle → capacités déclarées (p. ex. ['completion', 'tools']) ; None si non déclarées."""
        return {m["name"]: m.get("capabilities") for m in self._requete("/api/tags").get("models", [])}

    def chat(self, corps: dict) -> dict:
        return self._requete("/api/chat", corps)


class ConversationOllama:
    def __init__(self, config: Config, client: ClientOllama, avec_outils: bool):
        self.config = config
        self.client = client
        self.avec_outils = avec_outils
        self.messages: list = [{"role": "system", "content": SYSTEME}]

    @property
    def utilise_outils(self) -> bool:
        return self.avec_outils

    def _chat(self, **extra) -> dict:
        return self.client.chat({
            "model": self.config.ollama_modele,
            "messages": self.messages,
            "stream": False,
            # Le contexte par défaut d'Ollama est trop court pour une demande + références.
            "options": {"num_ctx": self.config.ollama_num_ctx, "temperature": 0.2},
            **extra,
        })

    def ajouter_utilisateur(self, texte: str) -> None:
        self.messages.append({"role": "user", "content": texte})

    def tour(self) -> Tour:
        rep = self._chat(tools=OUTILS_OLLAMA)
        message = rep.get("message", {})
        self.messages.append({k: v for k, v in message.items() if k in ("role", "content", "tool_calls")})
        t = Tour(jetons_entree=rep.get("prompt_eval_count", 0), jetons_sortie=rep.get("eval_count", 0))
        for appel in message.get("tool_calls") or []:
            fn = appel.get("function", {})
            args = fn.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {"_brut": args}
            t.appels.append(Appel(appel.get("id") or uuid.uuid4().hex[:12], fn.get("name", ""), args))
        if rep.get("done_reason") == "length" and not t.appels:
            t.arret, t.detail = "tronque", "Réponse tronquée (contexte ou limite de génération atteinte)."
        else:
            t.arret = "outils" if t.appels else "fin"
        return t

    def ajouter_resultats(self, resultats: list[tuple[Appel, str, bool]]) -> None:
        for appel, contenu, est_erreur in resultats:
            self.messages.append({"role": "tool", "tool_name": appel.nom,
                                  "content": f"ERREUR : {contenu}" if est_erreur else contenu})

    def forcer_analyse(self) -> tuple[dict | None, Tour]:
        """Repli des petits modèles : sortie structurée imposée par le schéma JSON de l'analyse."""
        self.messages.append({"role": "user", "content": CONSIGNE_JSON})
        rep = self._chat(format=SCHEMA_ANALYSE_BORNE)
        t = Tour(jetons_entree=rep.get("prompt_eval_count", 0), jetons_sortie=rep.get("eval_count", 0))
        try:
            return json.loads(rep.get("message", {}).get("content", "")), t
        except json.JSONDecodeError:
            return None, t


def moteur_ollama(config: Config):
    client = ClientOllama(config.ollama_url, config.ollama_timeout, config.ollama_api_key)
    disponibles = client.modeles()
    if config.ollama_modele not in disponibles and normaliser_modele(config.ollama_modele) in disponibles:
        config = replace(config, ollama_modele=normaliser_modele(config.ollama_modele))
    if config.ollama_modele not in disponibles:
        liste = ", ".join(disponibles) or "aucun"
        raise MoteurIndisponible(
            f"Modèle Ollama « {config.ollama_modele} » introuvable. Installés : {liste}. "
            f"Installez-le avec « ollama pull {config.ollama_modele} » ou choisissez-en un avec --modele-ollama."
        )
    capacites = disponibles[config.ollama_modele]
    # Capacités non déclarées (certains serveurs distants) : on tente les outils, avec repli JSON.
    avec_outils = capacites is None or "tools" in capacites
    return lambda: ConversationOllama(config, client, avec_outils)


def creer_moteur(config: Config):
    """Retourne une fabrique de conversations pour le fournisseur configuré."""
    if config.fournisseur == "ollama":
        return moteur_ollama(config)
    return moteur_claude(config)


def libelle_moteur(config: Config) -> str:
    if config.fournisseur == "ollama":
        lieu = "local" if est_adresse_locale(config.ollama_url) else "distant"
        return f"Ollama {lieu} · {config.ollama_modele} ({masquer_identifiants(config.ollama_url)})"
    return f"Claude · {config.modele} (effort « {config.effort} »)"
