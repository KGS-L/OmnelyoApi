"""
Handlers des commandes et des messages du bot Telegram.
Implémenté avec python-telegram-bot (async/await).
"""
import asyncio
import html
import logging
import uuid
from pathlib import Path
from telegram import BotCommand, Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

import config
from bot import oauth_server
from core import youtube_auth

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

WELCOME_UNLINKED = (
    "👋 <b>Welcome to ShortPilot Assistant</b>\n\n"
    "Create, schedule and publish content across YouTube, TikTok, Instagram "
    "and Facebook.\n\n"
    "🔐 <b>Connect your ShortPilot account to continue</b>\n\n"
    f'1. <a href="{html.escape(config.WEB_APP_URL, quote=True)}">Open the ShortPilot web app</a> and sign in.\n'
    "2. Open <b>Settings → Integrations → Telegram</b>.\n"
    "3. Select <b>Connect Telegram</b>.\n"
    "4. Return here through the secure one-time link.\n\n"
    "ShortPilot will never ask for your password or payment details in Telegram.\n\n"
    f'🌐 <a href="{html.escape(config.WEB_APP_URL, quote=True)}">{html.escape(config.WEB_APP_URL)}</a>'
)

WELCOME_LINKED = (
    "✅ <b>Your Telegram account is connected to ShortPilot.</b>\n\n"
    "You can send a content URL or upload a video to add it to your workspace. "
    "Choose its destinations and publication settings from the web app.\n\n"
    "<b>Commands</b>\n"
    "• /status — Check your ShortPilot connection\n"
    "• /queue — View recent processing jobs\n"
    "• /cancel ID — Cancel a queued job\n"
    "• /help — Show this help message\n"
    "• /disconnect — Disconnect Telegram from ShortPilot"
)


async def _has_shortpilot_account(telegram_user_id: int) -> bool:
    def lookup() -> bool:
        from api.database import SessionLocal
        from api.integrations.telegram import get_active_telegram_connection

        with SessionLocal() as db:
            return get_active_telegram_connection(db, telegram_user_id) is not None

    return await asyncio.to_thread(lookup)


async def _require_shortpilot_account(update: Update) -> bool:
    try:
        connected = await _has_shortpilot_account(update.effective_user.id)
    except Exception:
        logger.exception("Unable to verify the Telegram account link")
        await update.effective_message.reply_text(
            "❌ ShortPilot could not verify your account. Please try again later."
        )
        return False
    if not connected:
        await update.effective_message.reply_text(WELCOME_UNLINKED, parse_mode="HTML")
        return False
    return True

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show onboarding or the authenticated command menu."""
    if context.args and context.args[0].startswith("link_"):
        await _link_web_account(update, context.args[0][5:])
        return
    try:
        connected = await _has_shortpilot_account(update.effective_user.id)
    except Exception:
        logger.exception("Unable to load Telegram onboarding status")
        connected = False
    await update.message.reply_text(
        WELCOME_LINKED if connected else WELCOME_UNLINKED,
        parse_mode="HTML",
    )


async def _link_web_account(update: Update, token: str) -> None:
    """Consomme le jeton web et associe le compte Telegram au workspace."""
    if not token:
        await update.message.reply_text("❌ This connection link is invalid.")
        return

    def attach():
        from redis import Redis

        from api.config import get_settings
        from api.database import SessionLocal
        from api.integrations.telegram import TelegramLinkService, attach_telegram_account

        settings = get_settings()
        pending = TelegramLinkService(
            Redis.from_url(settings.redis_url), settings.telegram_link_ttl_seconds
        ).consume(token)
        if pending is None:
            raise ValueError("This link is invalid, expired or has already been used.")
        with SessionLocal() as db:
            attach_telegram_account(
                db,
                pending,
                telegram_user_id=update.effective_user.id,
                telegram_chat_id=update.effective_chat.id,
            )

    try:
        await asyncio.to_thread(attach)
    except ValueError as exc:
        await update.message.reply_text(f"❌ {html.escape(str(exc))}", parse_mode="HTML")
        return
    except Exception:
        logger.exception("Échec de liaison du compte Telegram au compte web")
        await update.message.reply_text(
            "❌ Connection failed. Generate a new Telegram link from ShortPilot."
        )
        return
    await update.message.reply_text(
        "✅ <b>Telegram is now connected to your ShortPilot account.</b>\n\n"
        "You can return to the web app or use /help to view available commands.",
        parse_mode="HTML",
    )


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
    """Show the authenticated ShortPilot integration status."""
    if not await _require_shortpilot_account(update):
        return
    await update.message.reply_text(
        "📊 <b>ShortPilot status</b>\n\n"
        "Account connection: ✅ Active\n"
        "Processing pipeline: ✅ Available\n"
        f"Workspace timezone: {config.TIMEZONE}\n\n"
        "Open the web app to manage social accounts and publication settings.",
        parse_mode="HTML",
    )


async def cmd_disconnect(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Déconnecte la chaîne YouTube en supprimant le token."""
    user_id = update.effective_user.id
    
    if youtube_auth.revoke_connection(user_id=user_id):
        await update.message.reply_text("🔌 Déconnecté de YouTube. Utilise /connect_youtube pour reconnecter.")
    else:
        await update.message.reply_text("ℹ️ Aucune connexion YouTube active à déconnecter.")


async def cmd_disconnect_shortpilot(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Révoque la liaison entre Telegram et le compte web ShortPilot."""
    def revoke() -> bool:
        from api.database import SessionLocal
        from api.integrations.telegram import revoke_telegram_account

        with SessionLocal() as db:
            return revoke_telegram_account(db, update.effective_user.id)

    try:
        revoked = await asyncio.to_thread(revoke)
    except Exception:
        logger.exception("Échec de révocation de la liaison ShortPilot")
        await update.message.reply_text("❌ La déconnexion a échoué. Réessaie plus tard.")
        return
    if revoked:
        await update.message.reply_text(
            "🔌 Telegram has been disconnected from ShortPilot.\n"
            "Reconnect it from Settings → Integrations → Telegram in the web app."
        )
    else:
        await update.message.reply_text("ℹ️ This Telegram account is not connected to ShortPilot.")


async def cmd_queue(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Affiche les derniers jobs de l'utilisateur."""
    if not await _require_shortpilot_account(update):
        return

    def load_jobs():
        from api.database import SessionLocal
        from api.integrations.telegram_jobs import list_jobs_for_telegram

        with SessionLocal() as db:
            return list_jobs_for_telegram(db, update.effective_user.id)

    try:
        jobs = await asyncio.to_thread(load_jobs)
    except ValueError as exc:
        await update.message.reply_text(f"❌ {html.escape(str(exc))}", parse_mode="HTML")
        return
    if not jobs:
        await update.message.reply_text("📭 Your processing queue is empty.")
        return
    icons = {
        "queued": "⏳",
        "running": "⚙️",
        "succeeded": "✅",
        "failed": "❌",
        "cancelled": "🚫",
    }
    lines = ["📋 <b>Your recent processing jobs</b>"]
    for job in jobs:
        job_status = job.status.value
        lines.append(
            f"{icons.get(job_status, '•')} <code>#{job.id}</code> "
            f"{job.type.value} — {job_status} ({job.progress} %)"
        )
    lines.append("\nCancel: <code>/cancel ID</code> (queued jobs only).")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Annule un job appartenant à l'utilisateur s'il n'a pas commencé."""
    if not await _require_shortpilot_account(update):
        return
    if not context.args:
        await update.message.reply_text("Usage: /cancel UUID")
        return
    try:
        job_id = uuid.UUID(context.args[0].lstrip("#"))
    except ValueError:
        await update.message.reply_text("❌ L'identifiant du traitement est invalide.")
        return

    def cancel():
        from api.database import SessionLocal
        from api.integrations.telegram_jobs import cancel_job_from_telegram

        with SessionLocal() as db:
            return cancel_job_from_telegram(db, update.effective_user.id, job_id)

    try:
        cancelled = await asyncio.to_thread(cancel)
    except ValueError as exc:
        await update.message.reply_text(f"❌ {html.escape(str(exc))}", parse_mode="HTML")
        return
    if cancelled:
        await update.message.reply_text(f"🚫 Traitement #{job_id} annulé.")
    else:
        await update.message.reply_text(
            "Impossible d'annuler : job introuvable, déjà lancé ou ne t'appartenant pas."
        )


# =============================================================================
# TRAITEMENT DU LIEN VIDÉO
# =============================================================================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gère la réception des messages textes (liens vidéos ou texte inconnu)."""
    if not await _require_shortpilot_account(update):
        return
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    if text.startswith("http://") or text.startswith("https://"):
        await update.message.reply_text(
            "⏳ <b>Lien vidéo reçu !</b>\n\n"
            "Je l'ajoute à la file d'attente et lance le traitement. Tu seras notifié une fois terminé.",
            parse_mode="HTML"
        )
        
        try:
            def enqueue():
                from redis import Redis
                from api.config import get_settings
                from api.database import SessionLocal
                from api.integrations.telegram_jobs import enqueue_url_from_telegram
                from workers.signals import notify_workers

                settings = get_settings()
                with SessionLocal() as db:
                    job = enqueue_url_from_telegram(db, user_id, text)
                notify_workers(Redis.from_url(settings.redis_url), str(job.id))
                return job

            job = await asyncio.to_thread(enqueue)
        except ValueError as exc:
            await update.message.reply_text(f"❌ {html.escape(str(exc))}", parse_mode="HTML")
            return
        except Exception as e:
            logger.exception("Erreur lors de l'insertion en DB")
            await update.message.reply_text(f"❌ Erreur de base de données : {e}")
            return

        await update.message.reply_text(f"📋 Traitement ajouté à la file : #{job.id}")
        
    else:
        await update.message.reply_text(
            "🤔 Je n'ai pas compris. Envoie-moi un lien de vidéo valide ou utilise /help pour voir les commandes."
        )


async def handle_video_upload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Télécharge, valide et met en file un Short envoyé dans Telegram."""
    if not await _require_shortpilot_account(update):
        return
    from bot.upload_helpers import parse_upload_caption, validate_uploaded_short

    message = update.effective_message
    user_id = update.effective_user.id
    media = message.video or message.document

    if message.document and not (message.document.mime_type or "").startswith("video/"):
        await message.reply_text("❌ Ce document n'est pas identifié comme une vidéo.")
        return

    max_bytes = config.TELEGRAM_UPLOAD_MAX_MB * 1024 * 1024
    if media.file_size is None:
        await message.reply_text("❌ Telegram n'a pas fourni la taille du fichier.")
        return
    if media.file_size > max_bytes:
        await message.reply_text(
            f"❌ Vidéo trop volumineuse : maximum {config.TELEGRAM_UPLOAD_MAX_MB} Mo."
        )
        return

    try:
        upload_request = parse_upload_caption(message.caption)
    except ValueError as exc:
        await message.reply_text(f"❌ {html.escape(str(exc))}", parse_mode="HTML")
        return

    suffix = Path(getattr(media, "file_name", "") or "short.mp4").suffix.lower()
    if suffix not in {".mp4", ".mov", ".m4v", ".webm"}:
        suffix = ".mp4"
    destination = (
        config.TMP_DIR
        / f"telegram_{user_id}_{message.message_id}_{media.file_unique_id}{suffix}"
    )

    await message.reply_text("⬇️ Téléchargement et vérification du Short…")
    try:
        telegram_file = await context.bot.get_file(media.file_id)
        await telegram_file.download_to_drive(custom_path=destination)
        duration, width, height = await asyncio.to_thread(validate_uploaded_short, destination)

        def persist_upload():
            from api.database import SessionLocal
            from api.integrations.telegram_jobs import import_video_from_telegram
            from api.media_upload import detect_video_type

            with destination.open("rb") as uploaded_file:
                mime_type, _ = detect_video_type(uploaded_file.read(32))
            with SessionLocal() as db:
                return import_video_from_telegram(
                    db, user_id, destination, mime_type,
                    duration, upload_request.title,
                )

        video = await asyncio.to_thread(persist_upload)
    except Exception as exc:
        destination.unlink(missing_ok=True)
        logger.exception("Échec de réception du Short Telegram")
        await message.reply_text(f"❌ Vidéo refusée : {html.escape(str(exc))}", parse_mode="HTML")
        return
    destination.unlink(missing_ok=True)

    schedule_label = (
        "à confirmer dans l'interface web ("
        + upload_request.publish_at.strftime("%d/%m/%Y à %H:%M")
        + ")"
        if upload_request.publish_at
        else "prochain créneau disponible"
    )
    await message.reply_text(
        f"✅ Short accepté ({width}×{height}, {duration:.1f}s).\n"
        f"📅 Publication : {schedule_label}\n"
        f"🎬 Titre : {upload_request.title}\n"
        f"📁 Vidéo importée : <code>{video.id}</code>\n"
        "Choisis maintenant ses plateformes de publication dans l'interface web."
        , parse_mode="HTML"
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
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("queue", cmd_queue))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CommandHandler("disconnect", cmd_disconnect_shortpilot))
    app.add_handler(MessageHandler(filters.VIDEO | filters.Document.VIDEO, handle_video_upload))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))


async def post_init(app: Application) -> None:
    """Appelé par l'Application de python-telegram-bot une fois la boucle lancée."""
    global _loop
    _loop = asyncio.get_running_loop()
    await app.bot.set_my_commands(
        [
            BotCommand("start", "Start ShortPilot Assistant"),
            BotCommand("help", "View available commands"),
            BotCommand("status", "Check your ShortPilot connection"),
            BotCommand("queue", "View recent processing jobs"),
            BotCommand("cancel", "Cancel a queued job"),
            BotCommand("disconnect", "Disconnect Telegram from ShortPilot"),
        ]
    )
    logger.info("Boucle d'événements du bot récupérée avec succès dans post_init")


def start_bot() -> None:
    """Point d'entrée synchrone utilisé par main.py pour démarrer le bot."""
    from bot.telegram_bot import run_bot
    run_bot()
