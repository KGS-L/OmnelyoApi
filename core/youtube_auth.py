"""
Authentification OAuth2 pour l'API YouTube Data v3 — flow "Web application".

Contrairement au flow Desktop (navigateur local), ici :
- generate_auth_url() crée un lien que le bot Telegram envoie à l'utilisateur
- l'utilisateur clique le lien depuis N'IMPORTE QUEL navigateur
- Google redirige vers YOUTUBE_REDIRECT_URI (le VPS, en HTTPS)
- exchange_code_for_token() complète l'échange côté serveur

Ce module ne dépend PAS de Telegram : il expose juste les fonctions OAuth.
Le petit serveur web qui reçoit le callback est dans bot/oauth_server.py.
"""
import logging
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build, Resource

import config

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
]

# Stockage temporaire des states OAuth (anti-CSRF)
# En production multi-instance : remplacer par Redis
# Structure: {state: (expiry: datetime, user_id: int|None)}
_pending_states: dict[str, tuple[datetime, int | None]] = {}


def _build_flow() -> Flow:
    """Construit le flow OAuth2 avec la configuration du projet."""
    flow = Flow.from_client_secrets_file(
        str(config.YOUTUBE_CLIENT_SECRETS_FILE),
        scopes=SCOPES,
        redirect_uri=config.YOUTUBE_REDIRECT_URI,
    )
    
    # Sécurité : forcer HTTPS en production
    if os.getenv("ENV") == "production" and not config.YOUTUBE_REDIRECT_URI.startswith("https://"):
        raise RuntimeError("YOUTUBE_REDIRECT_URI doit utiliser HTTPS en production")
    
    return flow


def generate_auth_url(user_id: int | None = None) -> tuple[str, str]:
    """
    Génère l'URL à envoyer à l'utilisateur via Telegram.
    Retourne (auth_url, state) — `state` sert à sécuriser le callback (anti-CSRF).
    """
    flow = _build_flow()
    auth_url, state = flow.authorization_url(
        access_type="offline",      # nécessaire pour obtenir un refresh_token
        include_granted_scopes="true",
        prompt="consent",            # force le renvoi du refresh_token
    )
    
    # Stocker le state avec expiration (10 minutes) et user_id associé
    _pending_states[state] = (datetime.now() + timedelta(minutes=10), user_id)
    
    logger.info("Auth URL générée", extra={"user_id": user_id})
    return auth_url, state


def exchange_code_for_token(code: str, state: str, user_id: int | None = None) -> None:
    """
    Appelé par le serveur callback (bot/oauth_server.py) une fois le `code`
    reçu de Google. Échange le code contre des credentials et les sauvegarde.
    
    Lève RuntimeError en cas de problème (state invalide, échec Google, etc.)
    """
    # --- Validation CSRF du state ---
    if state not in _pending_states:
        logger.warning("State invalide ou inconnu", extra={"state_prefix": state[:8] if state else None})
        raise RuntimeError("Session invalide ou expirée. Recommence avec /connect_youtube.")
    
    expiry, expected_user_id = _pending_states.pop(state)
    
    # Vérifier expiration
    if datetime.now() > expiry:
        raise RuntimeError("Le lien a expiré (10 minutes). Recommence avec /connect_youtube.")
    
    # Vérifier cohérence user_id (si fourni)
    if user_id is not None and expected_user_id is not None and user_id != expected_user_id:
        logger.warning("Mismatch user_id", extra={"expected": expected_user_id, "got": user_id})
        raise RuntimeError("Session utilisateur invalide.")
    
    # --- Échange OAuth avec Google ---
    flow = _build_flow()
    try:
        flow.fetch_token(code=code)
    except Exception as e:
        logger.exception("Échec échange token Google")
        raise RuntimeError(f"Échec de l'authentification Google : {e}")
    
    creds = flow.credentials
    
    # --- Persistance atomique du token ---
    token_path = _token_path(user_id)
    token_path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(token_path, creds.to_json())
    
    logger.info(
        "Token sauvegardé",
        extra={"user_id": user_id, "has_refresh": bool(creds.refresh_token)}
    )


def _token_path(user_id: int | None) -> Path:
    """Détermine le chemin du fichier token selon le mode single/multi-user."""
    if user_id is None:
        return config.YOUTUBE_TOKEN_FILE
    return config.YOUTUBE_TOKEN_FILE.parent / f"youtube_{user_id}.json"


def _atomic_write(path: Path, content: str) -> None:
    """
    Écriture atomique : évite la corruption si crash pendant l'écriture.
    Utilise mkstemp + rename(2) qui est atomique sur POSIX.
    """
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(content)
            f.flush()
            os.fsync(fd)  # S'assurer que les données sont sur disque
        os.replace(tmp_path, path)  # Atomique
    except Exception:
        # Nettoyer le fichier temporaire en cas d'erreur
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def is_connected(user_id: int | None = None) -> bool:
    """Vérifie si un token valide (ou rafraîchissable) existe."""
    token_path = _token_path(user_id)
    
    if not token_path.exists():
        return False
    
    try:
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
        return creds.valid or bool(creds.refresh_token)
    except Exception:
        return False


def get_credentials(user_id: int | None = None) -> Credentials:
    """
    Charge les credentials sauvegardés et les rafraîchit si besoin.
    Lève RuntimeError si aucun token n'existe (l'appelant doit proposer /connect_youtube).
    """
    token_path = _token_path(user_id)
    
    if not token_path.exists():
        raise RuntimeError(
            "Aucun token YouTube trouvé. Lance /connect_youtube dans le bot Telegram."
        )

    creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds.valid:
        if creds.expired and creds.refresh_token:
            logger.info("Rafraîchissement du token...")
            creds.refresh(Request())
            _atomic_write(token_path, creds.to_json())
            logger.info("Token rafraîchi avec succès")
        else:
            raise RuntimeError(
                "Token YouTube invalide et non rafraîchissable. "
                "Relance /connect_youtube dans le bot Telegram."
            )

    return creds


def get_youtube_service(user_id: int | None = None) -> Resource:
    """Retourne un client YouTube API prêt à l'emploi (authentifié)."""
    creds = get_credentials(user_id)
    return build("youtube", "v3", credentials=creds)


def revoke_connection(user_id: int | None = None) -> bool:
    """
    Supprime le token local. Ne révoque PAS côté Google (le token reste valide
    jusqu'à expiration, mais devient inutilisable pour cette application).
    Retourne True si un fichier existait et a été supprimé.
    """
    token_path = _token_path(user_id)
    if token_path.exists():
        token_path.unlink()
        logger.info("Token supprimé", extra={"user_id": user_id})
        return True
    return False