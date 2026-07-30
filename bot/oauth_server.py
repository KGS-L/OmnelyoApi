"""
Petit serveur web (Flask) qui écoute UNIQUEMENT la route /oauth2callback.
Tourne en parallèle du bot Telegram (thread séparé), derrière un reverse
proxy HTTPS (Caddy recommandé) sur le VPS.

Ce serveur ne fait qu'une chose : recevoir le `code` que Google renvoie
après que l'utilisateur ait accepté les permissions, puis appeler
core.youtube_auth.exchange_code_for_token() pour finaliser la connexion.
"""
import threading
from flask import Flask, request

import config
from core import youtube_auth

app = Flask(__name__)

# Callback optionnel pour notifier le bot Telegram une fois la connexion faite
_on_connected_callback = None


def set_on_connected_callback(callback) -> None:
    """Permet à bot/handlers.py d'enregistrer une notif Telegram post-connexion."""
    global _on_connected_callback
    _on_connected_callback = callback


@app.route("/oauth2callback")
def oauth2callback():
    code = request.args.get("code")
    error = request.args.get("error")

    if error:
        return f"❌ Autorisation refusée ou erreur : {error}", 400

    if not code:
        return "❌ Aucun code reçu de Google.", 400

    try:
        youtube_auth.exchange_code_for_token(code)
    except Exception as e:
        return f"❌ Erreur lors de l'échange du token : {e}", 500

    if _on_connected_callback:
        _on_connected_callback()

    return (
        "✅ Chaîne YouTube connectée avec succès ! "
        "Tu peux fermer cette page et retourner sur Telegram."
    )


def run_oauth_server() -> None:
    """À lancer dans un thread séparé au démarrage du bot (voir main.py)."""
    # 0.0.0.0 nécessaire pour être joignable depuis le conteneur Caddy
    # (le port n'est jamais exposé publiquement, seul Caddy y a accès via le réseau Docker interne)
    app.run(host="0.0.0.0", port=config.OAUTH_CALLBACK_PORT)


def start_in_background() -> None:
    thread = threading.Thread(target=run_oauth_server, daemon=True)
    thread.start()
