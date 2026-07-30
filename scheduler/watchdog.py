"""
Vérification périodique (Watchdog) :
- Vérifie les clips dont scheduled_publish_at est passé mais status != 'published'
- Alerte via le bot Telegram si problème détecté
"""
import logging
from datetime import datetime, timedelta

import config
from db.database import get_connection
from core import youtube_uploader
from scheduler.scheduler import send_telegram_notification, ZoneInfo

logger = logging.getLogger(__name__)


def check_scheduled_clips() -> None:
    """
    Requête la DB pour les clips en retard, vérifie leur statut réel
    via youtube_uploader.check_publish_status, et notifie en cas d'anomalie.
    """
    logger.info("Watchdog : Vérification des publications programmées en cours...")

    try:
        # Obtenir l'heure locale actuelle au format ISO 8601
        if ZoneInfo:
            now_str = datetime.now(ZoneInfo(config.TIMEZONE)).isoformat()
            now_dt = datetime.now(ZoneInfo(config.TIMEZONE))
        else:
            now_str = datetime.now().isoformat()
            now_dt = datetime.now()

        # Récupérer les clips programmés dont l'heure de publication est passée
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, youtube_video_id, scheduled_publish_at, status FROM clips "
                "WHERE status = 'scheduled' AND scheduled_publish_at <= ?",
                (now_str,)
            )
            delayed_clips = cursor.fetchall()

        if not delayed_clips:
            logger.info("Watchdog : Aucun clip planifié en retard à vérifier.")
            return

        logger.info(f"Watchdog : {len(delayed_clips)} clip(s) en retard détecté(s). Vérification sur YouTube...")

        for clip in delayed_clips:
            clip_id = clip["id"]
            yt_video_id = clip["youtube_video_id"]
            scheduled_at = clip["scheduled_publish_at"]

            if not yt_video_id:
                logger.warning(f"Clip #{clip_id} : Pas de youtube_video_id trouvé.")
                _update_clip_status(clip_id, "failed")
                send_telegram_notification(
                    f"⚠️ <b>[Watchdog]</b> Le clip #{clip_id} (prévu pour le {scheduled_at}) "
                    "n'a pas d'identifiant YouTube associé !"
                )
                continue

            try:
                # Vérifier le statut réel sur YouTube
                yt_status = youtube_uploader.check_publish_status(yt_video_id)
                logger.info(f"Watchdog : Clip #{clip_id} (YT ID: {yt_video_id}) -> Statut YT : {yt_status}")

                if yt_status == "public":
                    # Succès : la vidéo est publiée !
                    _update_clip_status(clip_id, "published")
                    send_telegram_notification(
                        f"📢 <b>[Watchdog] Succès !</b> Le clip #{clip_id} est maintenant public sur YouTube.\n"
                        f"🔗 <a href='https://youtube.com/shorts/{yt_video_id}'>Voir le Short</a>"
                    )
                elif yt_status in ["private", "unlisted"]:
                    # Encore privé, on tolère un petit délai (YouTube traite la publication)
                    # Si le retard excède 1h, on alerte l'admin
                    try:
                        # Si scheduled_at a une indication de fuseau horaire, fromisoformat le gère bien sous Python 3.11+
                        scheduled_dt = datetime.fromisoformat(scheduled_at)
                        
                        # Alerte si retard supérieur à 1 heure
                        if now_dt - scheduled_dt > timedelta(hours=1):
                            send_telegram_notification(
                                f"⚠️ <b>[Watchdog] Retard !</b> Le clip #{clip_id} (prévu le {scheduled_at}) "
                                f"est toujours privé/non listé (actuel : {yt_status}) après plus de 1h."
                            )
                    except Exception:
                        logger.exception(f"Impossible de parser la date du clip {clip_id} : {scheduled_at}")
                        
                elif yt_status == "not_found":
                    # Vidéo introuvable ou supprimée
                    _update_clip_status(clip_id, "failed")
                    send_telegram_notification(
                        f"❌ <b>[Watchdog] Erreur !</b> Le Short <code>{yt_video_id}</code> "
                        f"pour le clip #{clip_id} n'existe pas sur YouTube."
                    )
            except Exception as e:
                logger.exception(f"Watchdog : Impossible de vérifier le clip #{clip_id}")

    except Exception as e:
        logger.exception("Watchdog : Erreur générale d'exécution")


def _update_clip_status(clip_id: int, status: str) -> None:
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE clips SET status = ?, last_checked_at = datetime('now') WHERE id = ?",
                (status, clip_id)
            )
            conn.commit()
    except Exception:
        logger.exception(f"Watchdog : Impossible de mettre à jour le statut du clip {clip_id}")


def start_scheduler() -> None:
    """ Démarre le planificateur en tâche de fond pour le watchdog quotidien. """
    from apscheduler.schedulers.background import BackgroundScheduler
    scheduler = BackgroundScheduler()
    # Exécuter le watchdog toutes les heures
    scheduler.add_job(check_scheduled_clips, "interval", hours=1, id="youtube_watchdog")
    scheduler.start()
    logger.info("Planificateur BackgroundScheduler démarré. Job watchdog enregistré (toutes les heures).")
