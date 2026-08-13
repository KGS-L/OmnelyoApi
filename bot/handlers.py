"""
Handlers des commandes et des messages du bot Telegram.
Implémenté avec python-telegram-bot (async/await).
"""
import asyncio
import html
import logging
import uuid
from pathlib import Path
from telegram import Update
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

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Affiche le message d'accueil et d'aide."""
    if context.args and context.args[0].startswith("link_"):
        await _link_web_account(update, context.args[0][5:])
        return
    help_text = (
        "🤖 <b>ShortPilot</b>\n\n"
        "Je t'aide à créer et publier des shorts YouTube automatiquement.\n\n"
        "<b>Commandes disponibles :</b>\n"
        "• /connect_youtube — Connecter ta chaîne YouTube\n"
        "• /status — Vérifier l'état de la connexion\n"
        "• /queue — Voir tes traitements\n"
        "• /cancel ID — Annuler un traitement en attente\n"
        "• /disconnect — Déconnecter YouTube\n"
        "• /disconnect_shortpilot — Délier ce compte du site ShortPilot\n"
        "• /help — Afficher ce message\n\n"
        "<b>Créer depuis un lien :</b> envoie une URL YouTube/TikTok/etc.\n\n"
        "<b>Publier ton propre Short :</b> envoie une vidéo verticale de "
        f"{config.TELEGRAM_UPLOAD_MAX_MB} Mo maximum et "
        f"{config.UPLOADED_SHORT_MAX_DURATION_SEC // 60} minutes maximum.\n"
        "Légende facultative :\n"
        "• <code>auto | Mon titre</code>\n"
        "• <code>2026-08-20 17:00 | Mon titre</code>\n"
        f"Les dates utilisent le fuseau {config.TIMEZONE}."
    )
    await update.message.reply_text(help_text, parse_mode="HTML")


async def _link_web_account(update: Update, token: str) -> None:
    """Consomme le jeton web et associe le compte Telegram au workspace."""
    if not token:
        await update.message.reply_text("❌ Lien de connexion invalide.")
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
            raise ValueError("Ce lien est invalide, expiré ou déjà utilisé.")
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
        await update.message.reply_text("❌ La connexion a échoué. Génère un nouveau lien.")
        return
    await update.message.reply_text(
        "✅ <b>Telegram est maintenant connecté à ton compte ShortPilot.</b>\n\n"
        "Tu peux revenir dans l'interface web.",
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
    """Affiche le statut actuel de la connexion et des créneaux de publication."""
    user_id = update.effective_user.id
    youtube_ok = youtube_auth.is_connected(user_id=user_id)
    
    def web_connection_active() -> bool:
        from api.database import SessionLocal
        from api.integrations.telegram import get_active_telegram_connection

        with SessionLocal() as db:
            return get_active_telegram_connection(db, user_id) is not None

    try:
        shortpilot_connected = await asyncio.to_thread(web_connection_active)
    except Exception:
        logger.warning("Statut de liaison web indisponible", exc_info=True)
        shortpilot_connected = False
    
    status_text = (
        "📊 <b>État du bot</b>\n\n"
        f"YouTube : {'✅ Connecté' if youtube_ok else '❌ Non connecté'}\n"
        f"Compte web : {'✅ Connecté' if shortpilot_connected else '❌ Non connecté'}\n"
        "Pipeline : PostgreSQL / workers SaaS\n"
        f"Fuseau horaire : {config.TIMEZONE}"
    )
    await update.message.reply_text(status_text, parse_mode="HTML")


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
            "🔌 Ton compte Telegram est déconnecté du site ShortPilot.\n"
            "Tu peux le reconnecter depuis Paramètres → Intégrations → Telegram."
        )
    else:
        await update.message.reply_text("ℹ️ Ce compte Telegram n'est pas lié au site ShortPilot.")


async def cmd_queue(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Affiche les derniers jobs de l'utilisateur."""
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
        await update.message.reply_text("📭 Ta file de traitements est vide.")
        return
    icons = {
        "queued": "⏳",
        "running": "⚙️",
        "succeeded": "✅",
        "failed": "❌",
        "cancelled": "🚫",
    }
    lines = ["📋 <b>Tes derniers traitements</b>"]
    for job in jobs:
        job_status = job.status.value
        lines.append(
            f"{icons.get(job_status, '•')} <code>#{job.id}</code> "
            f"{job.type.value} — {job_status} ({job.progress} %)"
        )
    lines.append("\nAnnulation : <code>/cancel ID</code> (job en attente uniquement).")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Annule un job appartenant à l'utilisateur s'il n'a pas commencé."""
    if not context.args:
        await update.message.reply_text("Utilisation : /cancel UUID")
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
    app.add_handler(CommandHandler("connect_youtube", cmd_connect_youtube))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("queue", cmd_queue))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CommandHandler("disconnect", cmd_disconnect))
    app.add_handler(CommandHandler("disconnect_shortpilot", cmd_disconnect_shortpilot))
    app.add_handler(MessageHandler(filters.VIDEO | filters.Document.VIDEO, handle_video_upload))
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
