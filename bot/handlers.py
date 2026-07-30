"""
Handlers des commandes et messages du bot Telegram.

Commandes prévues :
- /status         -> état des vidéos en cours / programmées
- /pause          -> suspend la programmation automatique
- (message texte)  -> si c'est un lien YouTube, déclenche le pipeline
"""
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

from core import youtube_auth


async def handle_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    raise NotImplementedError


async def handle_connect_youtube(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Lance le flow OAuth : génère le lien d'autorisation Google et l'envoie.
    L'utilisateur clique, autorise, et le serveur callback (oauth_server.py)
    termine la connexion automatiquement.
    """
    if youtube_auth.is_connected():
        await update.message.reply_text(
            "✅ Une chaîne YouTube est déjà connectée. "
            "Relance /connect_youtube si tu veux changer de compte."
        )

    auth_url, _state = youtube_auth.generate_auth_url()
    await update.message.reply_text(
        "🔗 Clique ce lien pour connecter ta chaîne YouTube :\n\n"
        f"{auth_url}\n\n"
        "Une fois autorisé, je te confirme ici automatiquement."
    )


async def handle_youtube_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reçoit un lien YouTube, crée l'entrée source_videos, lance le pipeline."""
    raise NotImplementedError


def register_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("status", handle_status))
    app.add_handler(CommandHandler("connect_youtube", handle_connect_youtube))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_youtube_link))
