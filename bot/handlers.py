"""
Handlers des commandes et des messages du bot Telegram.
Implémenté avec python-telegram-bot (async/await).
"""
import asyncio
import logging
from pathlib import Path
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

import config
from bot import oauth_server
from core import youtube_auth
from scheduler import scheduler

logger = logging.getLogger(__name__)

# Références globales pour communiquer avec le bot depuis le thread Flask (OAuth Callback)
_application: Application | None = None
_loop: asyncio.AbstractEventLoop | None = None


# =============================================================================
# CALLBACK OAUTH (Notification après connexion YouTube réussie)
# =============================================================================

def _on_youtube_connected(user_id: int | None) -> None:
    """
    Appelé par oauth_server.py (depuis un thread Flask séparé)
    lorsque l'échange de token réussit.
    """
    if not user_id:
        logger.warning("Callback OAuth reçu sans user_id")
        return
        
    if not _application or not _loop:
        logger.warning(
            "Impossible d'envoyer la notification post-OAuth : "
            "l'application Telegram ou la boucle d'événements n'est pas initialisée."
        )
        return

    async def send_msg():
        try:
            await _application.bot.send_message(
                chat_id=user_id,
                text="✅ <b>Chaîne YouTube connectée avec succès !</b>\n\n"
                     "Tu peux maintenant m'envoyer un lien de vidéo pour commencer le traitement.",
                parse_mode="HTML"
            )
        except Exception:
            logger.exception("Échec de la notification de connexion YouTube au bot")

    # Planifie la coroutine sur la boucle d'événements principale du bot
    asyncio.run_coroutine_threadsafe(send_msg(), _loop)


# =============================================================================
# COMMANDES DU BOT
# =============================================================================

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Affiche le message d'accueil et d'aide."""
    help_text = (
        "🤖 <b>Robot Short YT</b>\n\n"
        "Je t'aide à créer et publier des shorts YouTube automatiquement.\n\n"
        "<b>Commandes disponibles :</b>\n"
        "• /connect_youtube — Connecter ta chaîne YouTube\n"
        "• /status — Vérifier l'état de la connexion\n"
        "• /disconnect — Déconnecter YouTube\n"
        "• /help — Afficher ce message\n\n"
        "Envoie-moi directement un lien de vidéo (YouTube/TikTok/etc.) pour commencer !"
    )
    await update.message.reply_text(help_text, parse_mode="HTML")


async def cmd_connect_youtube(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Génère et envoie le lien OAuth de connexion YouTube."""
    user_id = update.effective_user.id
    
    if youtube_auth.is_connected(user_id=user_id):
        await update.message.reply_text("✅ Ta chaîne YouTube est déjà connectée !")
        return

    try:
        auth_url, state = youtube_auth.generate_auth_url(user_id=user_id)
        
        await update.message.reply_text(
            "🔗 <b>Connexion YouTube</b>\n\n"
            "Clique sur le lien ci-dessous pour autoriser l'accès :\n"
            f'<a href="{auth_url}">Se connecter à YouTube</a>\n\n'
            "⏳ Tu as 10 minutes. Une fois fait, tu recevras une confirmation ici !",
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    except Exception as e:
        logger.exception("Erreur lors de la génération de l'URL OAuth")
        await update.message.reply_text(f"❌ Erreur : {e}")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Affiche le statut actuel de la connexion et des créneaux de publication."""
    user_id = update.effective_user.id
    youtube_ok = youtube_auth.is_connected(user_id=user_id)
    
    remaining = scheduler.get_remaining_slots(user_id)
    
    status_text = (
        "📊 <b>État du robot</b>\n\n"
        f"YouTube : {'✅ Connecté' if youtube_ok else '❌ Non connecté'}\n"
        f"Créneaux restants aujourd'hui : {remaining}/{config.MAX_CLIPS_PER_DAY}\n"
        f"Fuseau horaire : {config.TIMEZONE}\n"
        f"Horaires prévus : {', '.join(config.PUBLISH_SLOTS)}"
    )
    await update.message.reply_text(status_text, parse_mode="HTML")


async def cmd_disconnect(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Déconnecte la chaîne YouTube en supprimant le token."""
    user_id = update.effective_user.id
    
    if youtube_auth.revoke_connection(user_id=user_id):
        await update.message.reply_text("🔌 Déconnecté de YouTube. Utilise /connect_youtube pour reconnecter.")
    else:
        await update.message.reply_text("ℹ️ Aucune connexion YouTube active à déconnecter.")


# =============================================================================
# TRAITEMENT DU LIEN VIDÉO
# =============================================================================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gère la réception des messages textes (liens vidéos ou texte inconnu)."""
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    if text.startswith("http://") or text.startswith("https://"):
        if not youtube_auth.is_connected(user_id=user_id):
            await update.message.reply_text(
                "❌ <b>YouTube non connecté</b>\n\n"
                "Utilise d'abord /connect_youtube pour lier ta chaîne.",
                parse_mode="HTML"
            )
            return

        await update.message.reply_text(
            "⏳ <b>Lien vidéo reçu !</b>\n\n"
            "Je l'ajoute à la file d'attente et lance le traitement. Tu seras notifié une fois terminé.",
            parse_mode="HTML"
        )
        
        # Enregistrement en base de données
        from db.database import get_connection
        try:
            with get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO source_videos (source_url, status) VALUES (?, ?)",
                    (text, "pending")
                )
                source_video_id = cursor.lastrowid
                conn.commit()
        except Exception as e:
            logger.exception("Erreur lors de l'insertion en DB")
            await update.message.reply_text(f"❌ Erreur de base de données : {e}")
            return

        # Lancer le pipeline en tâche de fond (dans l'exécuteur de thread pour ne pas bloquer le bot)
        loop = asyncio.get_running_loop()
        loop.run_in_executor(None, scheduler.process_source_video, source_video_id)
        
    else:
        await update.message.reply_text(
            "🤔 Je n'ai pas compris. Envoie-moi un lien de vidéo valide ou utilise /help pour voir les commandes."
        )


# =============================================================================
# ENREGISTREMENT ET DEMARRAGE
# =============================================================================

def register_handlers(app: Application) -> None:
    """Enregistre tous les handlers de commandes et de messages."""
    global _application
    _application = app
    
    # Enregistrer le callback post-connexion auprès d'oauth_server
    oauth_server.set_on_connected_callback(_on_youtube_connected)
    
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CommandHandler("connect_youtube", cmd_connect_youtube))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("disconnect", cmd_disconnect))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))


async def post_init(app: Application) -> None:
    """Appelé par l'Application de python-telegram-bot une fois la boucle lancée."""
    global _loop
    _loop = asyncio.get_running_loop()
    logger.info("Boucle d'événements du bot récupérée avec succès dans post_init")


def start_bot() -> None:
    """Point d'entrée synchrone utilisé par main.py pour démarrer le bot."""
    from bot.telegram_bot import run_bot
    run_bot()