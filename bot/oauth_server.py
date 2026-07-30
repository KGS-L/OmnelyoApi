"""
Petit serveur web (Flask) qui écoute UNIQUEMENT la route /oauth2callback.
Tourne en parallèle du bot Telegram (thread séparé), derrière un reverse
proxy HTTPS (Caddy recommandé) sur le VPS.

Flux complet :
1. Bot génère URL OAuth avec state → envoie à l'utilisateur
2. Google redirige vers /oauth2callback?code=XXX&state=YYY
3. Serveur valide state (anti-CSRF), échange code contre token
4. Notifie le bot Telegram via callback, retourne page succès/erreur
"""
import logging
import threading
from http import HTTPStatus
from typing import Callable, Optional

from flask import Flask, request, jsonify

import config
from core import youtube_auth

logger = logging.getLogger(__name__)

app = Flask(__name__)

# Callback optionnel pour notifier le bot Telegram post-connexion
# Signature attendue: callback(user_id: int | None) -> None
_on_connected_callback: Optional[Callable] = None


def set_on_connected_callback(callback: Callable) -> None:
    """Permet à bot/handlers.py d'enregistrer une notif Telegram post-connexion."""
    global _on_connected_callback
    _on_connected_callback = callback


@app.route("/health", methods=["GET"])
def health_check() -> tuple[str, int]:
    """Endpoint pour monitoring Docker/Caddy (optionnel mais recommandé)."""
    return "ok", HTTPStatus.OK


@app.route("/oauth2callback")
def oauth2callback() -> tuple[str, int]:
    """
    Reçoit le callback OAuth2 de Google.
    Paramètres attendus: ?code=...&state=... (state obligatoire)
    """
    # --- Extraction et validation préliminaire ---
    code = request.args.get("code")
    state = request.args.get("state")
    error = request.args.get("error")
    user_id = request.args.get("user_id")  # optionnel, si multi-user

    # Log sécurisé (tronquer le code)
    code_prefix = code[:8] + "..." if code else None
    logger.info(
        "OAuth callback received",
        extra={
            "state_prefix": state[:8] if state else None,
            "code_prefix": code_prefix,
            "error": error,
            "remote_addr": request.remote_addr,
        },
    )

    # --- Cas d'erreur Google ---
    if error:
        logger.warning("OAuth error from Google", extra={"error": error})
        return _render_error_page(
            title="Autorisation refusée",
            message=f"Google a retourné une erreur : <code>{error}</code>",
            status=HTTPStatus.BAD_REQUEST,
        )

    # --- Validation des paramètres requis ---
    if not code:
        logger.warning("Missing code parameter")
        return _render_error_page(
            title="Paramètre manquant",
            message="Aucun code d'autorisation reçu de Google.",
            status=HTTPStatus.BAD_REQUEST,
        )

    if not state:
        logger.warning("Missing state parameter — possible CSRF attack")
        return _render_error_page(
            title="Sécurité : paramètre state manquant",
            message="La requête ne contient pas de token de sécurité (state). "
                    "Cela peut indiquer une tentative d'attaque.",
            status=HTTPStatus.BAD_REQUEST,
        )

    # --- Échange du code contre le token ---
    try:
        resolved_user_id = youtube_auth.exchange_code_for_token(
            code=code,
            state=state,
            user_id=int(user_id) if user_id else None,
        )
    except RuntimeError as e:
        # Erreurs métier (state invalide, token expiré, etc.)
        logger.warning("OAuth exchange failed: %s", e)
        return _render_error_page(
            title="Échec de l'authentification",
            message=str(e),
            status=HTTPStatus.BAD_REQUEST,
        )
    except Exception as e:
        # Erreurs système imprévues
        logger.exception("Unexpected error during OAuth exchange")
        return _render_error_page(
            title="Erreur technique",
            message="Une erreur inattendue s'est produite. Réessaie ou contacte le support.",
            status=HTTPStatus.INTERNAL_SERVER_ERROR,
        )

    # --- Succès : notification au bot ---
    logger.info("OAuth successful, notifying bot")
    if _on_connected_callback:
        try:
            _on_connected_callback(user_id=resolved_user_id)
        except Exception:
            logger.exception("Post-connection callback failed (non-critical)")

    return _render_success_page()


# --- Templates HTML minimaux ---

def _render_success_page() -> tuple[str, int]:
    """Page de succès, auto-fermeture possible via JavaScript."""
    html = """<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>✅ Connexion réussie</title>
    <style>
        body { font-family: system-ui, sans-serif; max-width: 500px; margin: 4rem auto; text-align: center; padding: 0 1rem; }
        .success { color: #16a34a; font-size: 4rem; margin-bottom: 0.5rem; }
        h1 { color: #1f2937; font-size: 1.5rem; }
        p { color: #6b7280; line-height: 1.6; }
        .btn { display: inline-block; margin-top: 1.5rem; padding: 0.75rem 1.5rem; 
               background: #16a34a; color: white; text-decoration: none; border-radius: 0.5rem; }
    </style>
</head>
<body>
    <div class="success">✅</div>
    <h1>Chaîne YouTube connectée !</h1>
    <p>Tu peux fermer cette page et retourner sur Telegram pour continuer.</p>
    <a class="btn" href="#" onclick="window.close()">Fermer la page</a>
</body>
</html>"""
    return html, HTTPStatus.OK


def _render_error_page(title: str, message: str, status: int) -> tuple[str, int]:
    """Page d'erreur structurée."""
    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>❌ Erreur</title>
    <style>
        body {{ font-family: system-ui, sans-serif; max-width: 500px; margin: 4rem auto; text-align: center; padding: 0 1rem; }}
        .error {{ color: #dc2626; font-size: 4rem; margin-bottom: 0.5rem; }}
        h1 {{ color: #1f2937; font-size: 1.5rem; }}
        .message {{ background: #fef2f2; border: 1px solid #fecaca; color: #991b1b; 
                    padding: 1rem; border-radius: 0.5rem; margin: 1rem 0; word-break: break-word; }}
        code {{ font-family: monospace; background: #f3f4f6; padding: 0.125rem 0.25rem; border-radius: 0.25rem; }}
        .btn {{ display: inline-block; margin-top: 1rem; padding: 0.75rem 1.5rem; 
                background: #dc2626; color: white; text-decoration: none; border-radius: 0.5rem; }}
    </style>
</head>
<body>
    <div class="error">❌</div>
    <h1>{title}</h1>
    <div class="message">{message}</div>
    <a class="btn" href="#" onclick="window.close()">Fermer</a>
</body>
</html>"""
    return html, status


# --- Démarrage du serveur ---

def run_oauth_server() -> None:
    """
    À lancer dans un thread séparé au démarrage du bot.
    0.0.0.0 nécessaire pour le conteneur Docker ; le port n'est JAMAIS
    exposé publiquement (Caddy uniquement via réseau interne).
    """
    # Réduire le logging Werkzeug (trop verbeux)
    import logging as _logging
    _logging.getLogger("werkzeug").setLevel(_logging.WARNING)

    logger.info(
        "Starting OAuth callback server",
        extra={"host": "0.0.0.0", "port": config.OAUTH_CALLBACK_PORT},
    )

    # threaded=True par défaut dans Flask, mais explicite ici
    app.run(
        host="0.0.0.0",
        port=config.OAUTH_CALLBACK_PORT,
        threaded=True,
        # debug=False IMPÉRATIF en production
        debug=False,
    )


def start_in_background() -> threading.Thread:
    """
    Démarre le serveur OAuth dans un daemon thread.
    Retourne le thread pour permettre un join() contrôlé si besoin.
    """
    thread = threading.Thread(target=run_oauth_server, daemon=True, name="oauth-server")
    thread.start()
    logger.info("OAuth server thread started")
    return thread