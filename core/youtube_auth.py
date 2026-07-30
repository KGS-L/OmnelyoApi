"""
Authentification OAuth2 pour l'API YouTube Data v3 — flow "Web application".

Contrairement au flow Desktop (navigateur local), ici :
- generate_auth_url() crée un lien que le bot Telegram envoie à l'utilisateur
- l'utilisateur clique le lien depuis N'IMPORTE QUEL navigateur (pas besoin
  d'accès direct à la machine qui héberge le script)
- Google redirige vers YOUTUBE_REDIRECT_URI (le VPS, en HTTPS)
- exchange_code_for_token() complète l'échange côté serveur

Ce module ne dépend PAS de Telegram : il expose juste les fonctions OAuth.
Le petit serveur web qui reçoit le callback est dans bot/oauth_server.py.
"""
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build, Resource

import config

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
]


def _build_flow() -> Flow:
    return Flow.from_client_secrets_file(
        str(config.YOUTUBE_CLIENT_SECRETS_FILE),
        scopes=SCOPES,
        redirect_uri=config.YOUTUBE_REDIRECT_URI,
    )


def generate_auth_url() -> tuple[str, str]:
    """
    Génère l'URL à envoyer à l'utilisateur via Telegram.
    Retourne (auth_url, state) — `state` sert à sécuriser/relier le callback
    (protection anti-CSRF standard du protocole OAuth2).
    """
    flow = _build_flow()
    auth_url, state = flow.authorization_url(
        access_type="offline",   # nécessaire pour obtenir un refresh_token
        include_granted_scopes="true",
        prompt="consent",         # force le renvoi du refresh_token à chaque fois
    )
    return auth_url, state


def exchange_code_for_token(code: str) -> None:
    """
    Appelé par le serveur callback (bot/oauth_server.py) une fois le `code`
    reçu de Google. Échange le code contre des credentials et les sauvegarde.
    """
    flow = _build_flow()
    flow.fetch_token(code=code)
    creds = flow.credentials

    config.YOUTUBE_TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    config.YOUTUBE_TOKEN_FILE.write_text(creds.to_json())


def is_connected() -> bool:
    """Vérifie si un token valide (ou rafraîchissable) existe déjà."""
    if not config.YOUTUBE_TOKEN_FILE.exists():
        return False
    try:
        creds = Credentials.from_authorized_user_file(
            str(config.YOUTUBE_TOKEN_FILE), SCOPES
        )
        return creds.valid or bool(creds.refresh_token)
    except Exception:
        return False


def get_credentials() -> Credentials:
    """
    Charge les credentials sauvegardés et les rafraîchit si besoin.
    Lève une erreur explicite si aucune connexion n'a encore été faite
    (l'appelant doit alors inviter l'utilisateur à faire /connect_youtube).
    """
    if not config.YOUTUBE_TOKEN_FILE.exists():
        raise RuntimeError(
            "Aucun token YouTube trouvé. Lance /connect_youtube dans le bot Telegram."
        )

    creds = Credentials.from_authorized_user_file(
        str(config.YOUTUBE_TOKEN_FILE), SCOPES
    )

    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            config.YOUTUBE_TOKEN_FILE.write_text(creds.to_json())
        else:
            raise RuntimeError(
                "Token YouTube invalide et non rafraîchissable. "
                "Relance /connect_youtube dans le bot Telegram."
            )

    return creds


def get_youtube_service() -> Resource:
    """Retourne un client YouTube API prêt à l'emploi (authentifié)."""
    creds = get_credentials()
    return build("youtube", "v3", credentials=creds)
