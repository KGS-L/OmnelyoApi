"""
Handlers de commandes et messages du bot Telegram.
Orchestre le flux : upload vidéo → traitement → upload YouTube.
"""
import logging
import os
from pathlib import Path

import telebot
from telebot.types import Message, CallbackQuery

import config
from bot import oauth_server
from core import youtube_auth, video_processor, uploader, scheduler

logger = logging.getLogger(__name__)

# Initialisation du bot
bot = telebot.TeleBot(config.TELEGRAM_BOT_TOKEN, parse_mode="HTML")

# État temporaire des conversations (en mémoire)
# En production : utiliser Redis ou la base de données
_user_states: dict[int, dict] = {}


# =============================================================================
# CALLBACK OAUTH (notification post-connexion YouTube)
# =============================================================================

def _on_youtube_connected(user_id: int | None) -> None:
    """Appelé par oauth_server.py quand la connexion YouTube réussit."""
    if user_id:
        try:
            bot.send_message(
                user_id,
                "✅ <b>Chaîne YouTube connectée !</b>\n\n"
                "Tu peux maintenant utiliser /upload pour publier des vidéos."
            )
        except Exception as e:
            logger.exception("Échec notification Telegram post-OAuth")


# Enregistrer le callback auprès du serveur OAuth
oauth_server.set_on_connected_callback(_on_youtube_connected)


# =============================================================================
# COMMANDES DE BASE
# =============================================================================

@bot.message_handler(commands=["start", "help"])
def cmd_start(message: Message) -> None:
    """Commande d'accueil et aide."""
    user_id = message.from_user.id
    
    help_text = (
        "🤖 <b>Robot Short YT</b>\n\n"
        "Je t'aide à créer et publier des shorts YouTube automatiquement.\n\n"
        "<b>Commandes disponibles :</b>\n"
        "• /connect_youtube — Connecter ta chaîne YouTube\n"
        "• /status — Vérifier l'état de la connexion\n"
        "• /upload — Uploader une vidéo (suivre les instructions)\n"
        "• /schedule — Voir/planifier les publications\n"
        "• /disconnect — Déconnecter YouTube\n\n"
        "Envoie-moi directement une vidéo pour la traiter !"
    )
    
    bot.reply_to(message, help_text)


@bot.message_handler(commands=["connect_youtube"])
def cmd_connect_youtube(message: Message) -> None:
    """Génère et envoie le lien OAuth pour connecter YouTube."""
    user_id = message.from_user.id
    
    # Vérifier si déjà connecté
    if youtube_auth.is_connected(user_id=user_id):
        bot.reply_to(message, "✅ Ta chaîne YouTube est déjà connectée !")
        return
    
    try:
        auth_url, state = youtube_auth.generate_auth_url(user_id=user_id)
        
        # Stocker le state pour vérification (déjà fait dans youtube_auth, mais double sécu)
        _user_states[user_id] = {"oauth_state": state, "step": "oauth_pending"}
        
        bot.reply_to(
            message,
            "🔗 <b>Connexion YouTube</b>\n\n"
            "Clique sur le lien ci-dessous pour autoriser l'accès :\n"
            f'<a href="{auth_url}">Se connecter à YouTube</a>\n\n'
            "⏳ Tu as 10 minutes. Une fois fait, reviens ici !",
            disable_web_page_preview=True,
        )
        
    except Exception as e:
        logger.exception("Erreur génération URL OAuth")
        bot.reply_to(message, f"❌ Erreur : {e}")


@bot.message_handler(commands=["status"])
def cmd_status(message: Message) -> None:
    """Affiche l'état des connexions et quotas."""
    user_id = message.from_user.id
    
    youtube_ok = youtube_auth.is_connected(user_id=user_id)
    
    status_text = (
        "📊 <b>État du robot</b>\n\n"
        f"YouTube : {'✅ Connecté' if youtube_ok else '❌ Non connecté'}\n"
        f"Quota clips aujourd'hui : {scheduler.get_remaining_slots(user_id)}/{config.MAX_CLIPS_PER_DAY}\n"
        f"Fuseau horaire : {config.TIMEZONE}\n"
        f"Créneaux de publication : {', '.join(config.PUBLISH_SLOTS)}"
    )
    
    bot.reply_to(message, status_text)


@bot.message_handler(commands=["disconnect"])
def cmd_disconnect(message: Message) -> None:
    """Déconnecte la chaîne YouTube."""
    user_id = message.from_user.id
    
    if youtube_auth.revoke_connection(user_id=user_id):
        bot.reply_to(message, "🔌 Déconnecté de YouTube. Utilise /connect_youtube pour reconnecter.")
    else:
        bot.reply_to(message, "ℹ️ Aucune connexion YouTube active.")


# =============================================================================
# UPLOAD ET TRAITEMENT DE VIDÉOS
# =============================================================================

@bot.message_handler(commands=["upload"])
def cmd_upload(message: Message) -> None:
    """Démarre le processus d'upload manuel."""
    user_id = message.from_user.id
    
    if not youtube_auth.is_connected(user_id=user_id):
        bot.reply_to(
            message,
            "❌ <b>YouTube non connecté</b>\n\n"
            "Utilise d'abord /connect_youtube pour lier ta chaîne."
        )
        return
    
    _user_states[user_id] = {"step": "awaiting_video"}
    
    bot.reply_to(
        message,
        "📤 <b>Upload de vidéo</b>\n\n"
        "Envoie-moi la vidéo que tu veux publier.\n"
        f"Format accepté : mp4, mov, avi\n"
        f"Durée conseillée : {config.CLIP_MIN_DURATION_SEC}-{config.CLIP_MAX_DURATION_SEC} secondes"
    )


@bot.message_handler(content_types=["video", "document"])
def handle_video(message: Message) -> None:
    """Réception et traitement d'une vidéo envoyée par l'utilisateur."""
    user_id = message.from_user.id
    
    # Vérifier connexion YouTube
    if not youtube_auth.is_connected(user_id=user_id):
        bot.reply_to(message, "❌ Connecte d'abord YouTube avec /connect_youtube")
        return
    
    # Vérifier état de conversation
    user_state = _user_states.get(user_id, {})
    if user_state.get("step") != "awaiting_video":
        # Mode rapide : traiter directement sans /upload explicite
        pass  # Continuer
    
    # Télécharger la vidéo
    bot.reply_to(message, "⏳ Téléchargement de la vidéo...")
    
    try:
        file_info = bot.get_file(message.video.file_id if message.video else message.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        # Sauvegarder temporairement
        tmp_path = config.TMP_DIR / f"{user_id}_{message.message_id}.mp4"
        config.TMP_DIR.mkdir(parents=True, exist_ok=True)
        tmp_path.write_bytes(downloaded_file)
        
        # Stocker dans l'état utilisateur
        _user_states[user_id] = {
            "step": "awaiting_metadata",
            "video_path": str(tmp_path),
            "file_size": len(downloaded_file),
        }
        
        bot.reply_to(
            message,
            "✅ Vidéo reçue !\n\n"
            "Envoie-moi maintenant les informations au format :\n\n"
            "<code>Titre de la vidéo\n"
            "Description optionnelle\n"
            "#tag1 #tag2</code>\n\n"
            "Ou envoie /skip pour utiliser les valeurs par défaut."
        )
        
    except Exception as e:
        logger.exception("Erreur téléchargement vidéo")
        bot.reply_to(message, f"❌ Erreur lors du téléchargement : {e}")


@bot.message_handler(commands=["skip"])
def cmd_skip_metadata(message: Message) -> None:
    """Utilise les métadonnées par défaut."""
    user_id = message.from_user.id
    user_state = _user_states.get(user_id, {})
    
    if user_state.get("step") != "awaiting_metadata":
        bot.reply_to(message, "ℹ️ Aucune vidéo en attente de métadonnées.")
        return
    
    _process_and_upload(user_id, title="Short automatique", description="", tags=[])


@bot.message_handler(func=lambda m: _user_states.get(m.from_user.id, {}).get("step") == "awaiting_metadata")
def handle_metadata(message: Message) -> None:
    """Parse les métadonnées et lance le traitement."""
    user_id = message.from_user.id
    
    # Parser le message : première ligne = titre, reste = description, #tags
    lines = message.text.strip().split("\n")
    title = lines[0][:100]  # Limite YouTube
    
    description = ""
    tags = []
    
    if len(lines) > 1:
        rest = "\n".join(lines[1:])
        # Extraire les hashtags
        tags = [tag.strip("#") for tag in rest.split() if tag.startswith("#")]
        description = rest[:5000]  # Limite YouTube
    
    _process_and_upload(user_id, title=title, description=description, tags=tags)


def _process_and_upload(user_id: int, title: str, description: str, tags: list[str]) -> None:
    """Pipeline complet : traitement vidéo + upload YouTube."""
    user_state = _user_states.get(user_id, {})
    video_path = Path(user_state["video_path"])
    
    bot.send_message(user_id, "🔧 Traitement de la vidéo en cours...")
    
    try:
        # 1. Traitement (optimisation short)
        processed_path = video_processor.process_for_short(video_path)
        
        # 2. Upload YouTube
        bot.send_message(user_id, "📤 Publication sur YouTube...")
        
        video_id = uploader.upload_to_youtube(
            video_path=processed_path,
            title=title,
            description=description,
            tags=tags,
            user_id=user_id,
        )
        
        # Nettoyage
        video_path.unlink(missing_ok=True)
        processed_path.unlink(missing_ok=True)
        _user_states.pop(user_id, None)
        
        # Notification succès
        bot.send_message(
            user_id,
            f"✅ <b>Vidéo publiée !</b>\n\n"
            f"🎬 {title}\n"
            f"🔗 https://youtube.com/shorts/{video_id}"
        )
        
    except Exception as e:
        logger.exception("Erreur pipeline upload")
        bot.send_message(user_id, f"❌ Erreur lors de la publication : {e}")
        # Garder les fichiers pour debug ? Optionnel


# =============================================================================
# PLANIFICATION ET AUTOMATISATION
# =============================================================================

@bot.message_handler(commands=["schedule"])
def cmd_schedule(message: Message) -> None:
    """Affiche ou modifie la planification."""
    user_id = message.from_user.id
    
    schedule_text = (
        "📅 <b>Planification</b>\n\n"
        f"Créneaux configurés : {', '.join(config.PUBLISH_SLOTS)}\n"
        f"Max par jour : {config.MAX_CLIPS_PER_DAY}\n\n"
        "Commandes de planification (à implémenter selon besoin) :\n"
        "• /auto_on — Activer la publication automatique\n"
        "• /auto_off — Désactiver\n"
        "• /next — Voir les prochains créneaux disponibles"
    )
    
    bot.reply_to(message, schedule_text)


# =============================================================================
# GESTION D'ERREURS ET MESSAGES INATTENDUS
# =============================================================================

@bot.message_handler(func=lambda m: True)
def handle_unknown(message: Message) -> None:
    """Réponse par défaut pour les messages non reconnus."""
    bot.reply_to(
        message,
        "🤔 Je n'ai pas compris. Utilise /help pour voir les commandes disponibles."
    )


# =============================================================================
# DÉMARRAGE
# =============================================================================

def start_bot() -> None:
    """Lance le polling Telegram (bloquant). À exécuter dans le thread principal."""
    logger.info("Démarrage du bot Telegram...")
    
    # Créer les dossiers nécessaires
    for dir_path in [config.TMP_DIR, config.PROCESSED_DIR, config.LOGS_DIR]:
        dir_path.mkdir(parents=True, exist_ok=True)
    
    # Démarrer le serveur OAuth en arrière-plan
    oauth_server.start_in_background()
    
    # Lancer le polling (bloquant)
    bot.infinity_polling()