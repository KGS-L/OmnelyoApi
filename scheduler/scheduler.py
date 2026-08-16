"""
Orchestration du pipeline complet + calcul des créneaux de publication.
"""
import logging
import shutil
import requests
from datetime import datetime, timedelta
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except ImportError:
    try:
        from pytz import timezone as ZoneInfo
    except ImportError:
        ZoneInfo = None

import config
from db.database import get_connection
from core import (
    downloader,
    scene_detect,
    video_cutter,
    video_processor,
    storytime,
    tts,
    overlay,
    storage_r2,
    youtube_uploader
)

logger = logging.getLogger(__name__)


def send_telegram_notification(message: str, chat_id: int | str | None = None) -> None:
    """
    Envoie une notification Telegram au chat ID administrateur configuré.
    Utilise l'API HTTP directement pour être thread-safe.
    """
    destination = chat_id or config.TELEGRAM_ADMIN_CHAT_ID
    if not config.TELEGRAM_BOT_TOKEN or not destination:
        logger.warning("Notification Telegram non envoyée : token ou chat_id manquant.")
        return
        
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": destination,
        "text": message,
        "parse_mode": "HTML"
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code != 200:
            logger.error(f"Échec de l'envoi de la notification Telegram: {response.text}")
    except Exception:
        logger.exception("Erreur lors de l'envoi de la notification Telegram")


def get_remaining_slots(user_id: int | None = None) -> int:
    """
    Retourne le nombre de créneaux de publication restants pour aujourd'hui.
    """
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM clips c "
                "JOIN source_videos s ON s.id = c.source_video_id "
                "WHERE date(c.scheduled_publish_at) = date('now') "
                "AND (? IS NULL OR s.telegram_user_id = ?)",
                (user_id, user_id),
            )
            count = cursor.fetchone()[0]
            return max(0, config.MAX_CLIPS_PER_DAY - count)
    except Exception:
        return config.MAX_CLIPS_PER_DAY


def get_next_available_slot(user_id: int | None = None) -> datetime:
    """
    Regarde la DB pour trouver le prochain créneau libre parmi
    config.PUBLISH_SLOTS, en respectant config.MAX_CLIPS_PER_DAY.
    """
    if ZoneInfo:
        local_tz = ZoneInfo(config.TIMEZONE)
        now_local = datetime.now(local_tz)
    else:
        now_local = datetime.now()
        local_tz = None
        
    day_offset = 0
    while True:
        check_day = now_local + timedelta(days=day_offset)

        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM clips c "
                "JOIN source_videos s ON s.id = c.source_video_id "
                "WHERE date(c.scheduled_publish_at) = ? AND c.status != 'failed' "
                "AND (? IS NULL OR s.telegram_user_id = ?)",
                (check_day.date().isoformat(), user_id, user_id),
            )
            scheduled_for_day = cursor.fetchone()[0]
        if scheduled_for_day >= config.MAX_CLIPS_PER_DAY:
            day_offset += 1
            continue
        
        for slot in config.PUBLISH_SLOTS:
            h, m = map(int, slot.split(":"))
            
            if local_tz:
                candidate = datetime(check_day.year, check_day.month, check_day.day, h, m, 0, tzinfo=local_tz)
            else:
                candidate = datetime(check_day.year, check_day.month, check_day.day, h, m, 0)
                
            # Ignorer les créneaux dans le passé
            if candidate <= now_local:
                continue
                
            candidate_str = candidate.isoformat()
            
            with get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT COUNT(*) FROM clips c "
                    "JOIN source_videos s ON s.id = c.source_video_id "
                    "WHERE c.scheduled_publish_at = ? AND c.status != 'failed' "
                    "AND (? IS NULL OR s.telegram_user_id = ?)",
                    (candidate_str, user_id, user_id),
                )
                count = cursor.fetchone()[0]
                
            if count == 0:
                return candidate
                
        day_offset += 1


def process_source_video(source_video_id: int) -> None:
    """
    Pipeline complet pour une vidéo source :
    download -> scene_detect -> cut -> storytime -> tts -> overlay
    -> upload R2 -> schedule sur YouTube -> notif Telegram
    """
    logger.info(f"Début du traitement de la vidéo source ID: {source_video_id}")
    
    source_url = None
    user_id = None
    chat_id = None
    local_video_path = None
    temp_files = []
    successful_clips = 0
    failed_clips = 0
    
    # 1. Récupérer l'URL source depuis la DB
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT source_url, telegram_user_id, telegram_chat_id "
                "FROM source_videos WHERE id = ?",
                (source_video_id,),
            )
            row = cursor.fetchone()
            if not row:
                logger.error(f"Vidéo source {source_video_id} non trouvée dans la DB.")
                return
            source_url = row["source_url"]
            user_id = row["telegram_user_id"]
            chat_id = row["telegram_chat_id"]
            
            # Mettre à jour le statut en 'downloading'
            cursor.execute(
                "UPDATE source_videos SET status = ? WHERE id = ?",
                ("downloading", source_video_id)
            )
            conn.commit()
    except Exception:
        logger.exception("Erreur DB à l'initialisation du pipeline")
        return

    send_telegram_notification(f"📥 <b>[Pipeline]</b> Démarrage du téléchargement pour la vidéo #{source_video_id}...", chat_id)

    # 2. Télécharger la vidéo source
    try:
        local_video_path = downloader.download_video(source_url, config.TMP_DIR)
        temp_files.append(local_video_path)
        
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE source_videos SET local_path = ?, status = ? WHERE id = ?",
                (str(local_video_path), "cutting", source_video_id)
            )
            conn.commit()
    except Exception as e:
        logger.exception("Échec du téléchargement de la vidéo source")
        send_telegram_notification(f"❌ <b>[Erreur]</b> Échec du téléchargement de la vidéo #{source_video_id} : {e}", chat_id)
        _mark_source_failed(source_video_id, str(e))
        return

    send_telegram_notification("✂️ <b>[Pipeline]</b> Analyse des scènes et découpage de la vidéo...", chat_id)

    # 3. Détecter les scènes et calculer les plages de découpage
    try:
        scenes = scene_detect.detect_scenes(local_video_path)
        clip_ranges = scene_detect.merge_scenes_to_clip_ranges(
            scenes,
            config.CLIP_MIN_DURATION_SEC,
            config.CLIP_MAX_DURATION_SEC
        )
        
        if not clip_ranges:
            raise RuntimeError("Aucune plage de clip n'a pu être générée à partir de la vidéo.")
            
        logger.info(f"{len(clip_ranges)} clips planifiés.")
    except Exception as e:
        logger.exception("Échec de la détection de scènes")
        send_telegram_notification(f"❌ <b>[Erreur]</b> Analyse des scènes impossible pour la vidéo #{source_video_id} : {e}", chat_id)
        _mark_source_failed(source_video_id, str(e))
        _cleanup_files(temp_files)
        return

    # 4. Traiter chaque clip individuellement
    for i, (start_sec, end_sec) in enumerate(clip_ranges, start=1):
        duration = end_sec - start_sec
        clip_id = None
        
        send_telegram_notification(f"🎥 <b>[Clip {i}/{len(clip_ranges)}]</b> Traitement du clip ({duration:.1f}s)...", chat_id)
        
        # Enregistrer le clip en DB comme 'draft'
        try:
            with get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO clips (source_video_id, sequence_order, duration_sec, status) VALUES (?, ?, ?, ?)",
                    (source_video_id, i, duration, "draft")
                )
                clip_id = cursor.lastrowid
                conn.commit()
        except Exception:
            logger.exception("Échec de la création du clip en DB")
            failed_clips += 1
            continue

        clip_temp_files = []
        try:
            # Mettre à jour l'état du clip en 'rendering'
            _update_clip_status(clip_id, "rendering")
            
            # A. Découper la vidéo (supprime l'audio original par défaut)
            raw_cut_path = config.TMP_DIR / f"src_{source_video_id}_clip_{i}_raw.mp4"
            video_cutter.cut_clip(local_video_path, start_sec, end_sec, raw_cut_path, remove_audio=True)
            clip_temp_files.append(raw_cut_path)
            
            # B. Adapter au format Short (9:16 vertical)
            processed_short_path = config.PROCESSED_DIR / f"src_{source_video_id}_clip_{i}_short.mp4"
            video_processor.process_for_short(raw_cut_path, processed_short_path)
            clip_temp_files.append(processed_short_path)
            
            # C. Générer le storytime narratif par l'IA
            theme = "histoire intrigante ou fait insolite"
            story_text = storytime.generate_story(theme, duration)
            
            # D. Générer la voix off TTS de l'histoire
            tts_audio_path = config.TMP_DIR / f"src_{source_video_id}_clip_{i}_tts.mp3"
            tts.generate_tts(story_text, tts_audio_path)
            clip_temp_files.append(tts_audio_path)
            
            # E. Générer la carte de commentaire visuelle
            card_image_path = config.TMP_DIR / f"src_{source_video_id}_clip_{i}_card.png"
            # Utilise les 100 premiers caractères pour le texte affiché dans l'overlay
            card_text = story_text[:120] + "..." if len(story_text) > 120 else story_text
            overlay.render_comment_card(card_text, card_image_path)
            clip_temp_files.append(card_image_path)
            
            # F. Superposer la carte et combiner la piste voix off
            final_clip_path = config.PROCESSED_DIR / f"short_final_{source_video_id}_{i}.mp4"
            overlay.overlay_card_on_video(
                processed_short_path,
                card_image_path,
                duration_sec=8,
                output_path=final_clip_path,
                audio_path=tts_audio_path
            )
            clip_temp_files.append(final_clip_path)
            
            # G. Téléverser vers R2
            r2_url = storage_r2.upload_to_r2(final_clip_path, f"shorts/short_{source_video_id}_{i}.mp4")
            
            # H. Calculer le créneau de publication YouTube
            publish_slot = get_next_available_slot(user_id)
            
            # I. Mettre en ligne et programmer sur YouTube
            yt_title = f"Une histoire incroyable ! Part {i} #shorts #storytime"
            yt_desc = f"{story_text}\n\n#shorts #storytime #history"
            
            send_telegram_notification(f"📤 <b>[Clip {i}/{len(clip_ranges)}]</b> Upload et programmation sur YouTube pour le {publish_slot.strftime('%d/%m à %H:%M')}...", chat_id)
            
            yt_video_id = youtube_uploader.upload_scheduled_short(
                video_path=final_clip_path,
                title=yt_title,
                description=yt_desc,
                publish_at=publish_slot,
                tags=["shorts", "storytime"],
                user_id=user_id,
            )
            
            # J. Extraire et envoyer la miniature YouTube
            try:
                thumb_path = video_processor.extract_thumbnail(final_clip_path, time_sec=1.0)
                youtube_uploader.update_video_thumbnail(yt_video_id, thumb_path, user_id=user_id)
                clip_temp_files.append(thumb_path)
            except Exception:
                logger.exception("Échec non critique de la mise à jour de la miniature")
                
            # K. Mettre à jour la DB
            with get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE clips SET local_path = ?, r2_url = ?, story_text = ?, tts_audio_path = ?, "
                    "youtube_video_id = ?, youtube_title = ?, scheduled_publish_at = ?, status = ? WHERE id = ?",
                    (
                        None,
                        r2_url,
                        story_text,
                        None,
                        yt_video_id,
                        yt_title,
                        publish_slot.isoformat(),
                        "scheduled",
                        clip_id
                    )
                )
                conn.commit()
                
            send_telegram_notification(
                f"✅ <b>[Clip {i}/{len(clip_ranges)}] Programmé !</b>\n"
                f"🎬 Titre : {yt_title}\n"
                f"📅 Publication : {publish_slot.strftime('%d/%m à %H:%M')}\n"
                f"🔗 YouTube ID : <code>{yt_video_id}</code>",
                chat_id,
            )
            successful_clips += 1
            
        except Exception as e:
            logger.exception(f"Échec du traitement du clip {i}")
            send_telegram_notification(f"❌ <b>[Erreur Clip {i}]</b> : {e}", chat_id)
            _update_clip_status(clip_id, "failed")
            failed_clips += 1
        finally:
            # Nettoyer les fichiers temporaires du clip pour libérer du disque
            _cleanup_files(clip_temp_files)

    # 5. Marquer la vidéo source comme terminée
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            if successful_clips and failed_clips:
                final_status = "partial"
            elif successful_clips:
                final_status = "done"
            else:
                final_status = "failed"
            cursor.execute(
                "UPDATE source_videos SET status = ? WHERE id = ?",
                (final_status, source_video_id)
            )
            conn.commit()
    except Exception:
        logger.exception("Échec marquage vidéo source terminée")

    # Nettoyage de la vidéo source
    _cleanup_files(temp_files)
    send_telegram_notification(
        f"🎉 <b>[Pipeline]</b> Vidéo #{source_video_id} terminée : "
        f"{successful_clips} clip(s) réussi(s), {failed_clips} échec(s).",
        chat_id,
    )


def process_uploaded_short(source_video_id: int) -> None:
    """Prépare et programme un Short fourni directement par l'utilisateur."""
    input_path = None
    processed_path = None
    clip_id = None
    chat_id = None
    try:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT telegram_user_id, telegram_chat_id, local_path, "
                "requested_publish_at, requested_title FROM source_videos "
                "WHERE id = ? AND source_type = 'upload'",
                (source_video_id,),
            ).fetchone()
            if not row:
                raise RuntimeError("Short importé introuvable.")
            user_id = row["telegram_user_id"]
            chat_id = row["telegram_chat_id"]
            input_path = Path(row["local_path"])
            title = (row["requested_title"] or "Mon Short #shorts")[:100]
            requested_publish_at = row["requested_publish_at"]
            conn.execute(
                "UPDATE source_videos SET status = 'publishing' WHERE id = ?",
                (source_video_id,),
            )
            conn.commit()

        if not input_path.exists():
            raise FileNotFoundError("Le fichier importé n'existe plus sur le serveur.")

        processed_path = config.PROCESSED_DIR / f"uploaded_short_{source_video_id}.mp4"
        video_processor.process_for_short(
            input_path,
            processed_path,
            max_duration=config.UPLOADED_SHORT_MAX_DURATION_SEC,
        )
        duration = float(
            video_processor._probe_video(processed_path).get("format", {}).get("duration", 0)
        )

        if requested_publish_at:
            publish_slot = datetime.fromisoformat(requested_publish_at)
        else:
            publish_slot = get_next_available_slot(user_id)

        # Le clip est créé avant l'upload : il réserve le créneau pour les autres jobs.
        with get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            scheduled_for_day = conn.execute(
                "SELECT COUNT(*) FROM clips c "
                "JOIN source_videos s ON s.id = c.source_video_id "
                "WHERE date(c.scheduled_publish_at) = ? AND c.status != 'failed' "
                "AND s.telegram_user_id = ?",
                (publish_slot.date().isoformat(), user_id),
            ).fetchone()[0]
            if scheduled_for_day >= config.MAX_CLIPS_PER_DAY:
                raise RuntimeError(
                    f"La limite de {config.MAX_CLIPS_PER_DAY} publication(s) pour cette "
                    "journée est déjà atteinte."
                )
            collision = conn.execute(
                "SELECT 1 FROM clips c JOIN source_videos s ON s.id = c.source_video_id "
                "WHERE c.scheduled_publish_at = ? AND c.status != 'failed' "
                "AND s.telegram_user_id = ? LIMIT 1",
                (publish_slot.isoformat(), user_id),
            ).fetchone()
            if collision:
                raise RuntimeError(
                    "Ce créneau est déjà réservé. Renvoie la vidéo avec une autre heure."
                )
            cursor = conn.execute(
                "INSERT INTO clips "
                "(source_video_id, sequence_order, duration_sec, youtube_title, "
                "scheduled_publish_at, status) VALUES (?, 1, ?, ?, ?, 'rendering')",
                (source_video_id, duration, title, publish_slot.isoformat()),
            )
            clip_id = cursor.lastrowid
            conn.commit()

        r2_url = storage_r2.upload_to_r2(
            processed_path, f"workspaces/telegram-{user_id}/uploads/{source_video_id}.mp4"
        )
        send_telegram_notification(
            f"📤 Upload YouTube du Short #{source_video_id} pour le "
            f"{publish_slot.strftime('%d/%m/%Y à %H:%M')}…",
            chat_id,
        )
        youtube_video_id = youtube_uploader.upload_scheduled_short(
            video_path=processed_path,
            title=title,
            description="#shorts",
            publish_at=publish_slot,
            tags=["shorts"],
            user_id=user_id,
        )

        with get_connection() as conn:
            conn.execute(
                "UPDATE clips SET local_path = NULL, r2_url = ?, youtube_video_id = ?, "
                "status = 'scheduled' WHERE id = ?",
                (r2_url, youtube_video_id, clip_id),
            )
            conn.execute(
                "UPDATE source_videos SET local_path = NULL, status = 'done' WHERE id = ?",
                (source_video_id,),
            )
            conn.commit()
        send_telegram_notification(
            f"✅ <b>Short programmé !</b>\n🎬 {title}\n"
            f"📅 {publish_slot.strftime('%d/%m/%Y à %H:%M')}\n"
            f"🔗 <code>{youtube_video_id}</code>",
            chat_id,
        )
    except Exception as exc:
        logger.exception("Échec du traitement du Short importé #%s", source_video_id)
        if clip_id is not None:
            _update_clip_status(clip_id, "failed")
        _mark_source_failed(source_video_id, str(exc))
        send_telegram_notification(f"❌ Échec du Short importé : {exc}", chat_id)
    finally:
        _cleanup_files([path for path in (input_path, processed_path) if path])


def _mark_source_failed(source_id: int, error_msg: str) -> None:
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE source_videos SET status = ?, error_message = ? WHERE id = ?",
                ("failed", error_msg[:500], source_id)
            )
            conn.commit()
    except Exception:
        logger.exception("Erreur lors du marquage en échec de la vidéo source")


def _update_clip_status(clip_id: int, status: str) -> None:
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE clips SET status = ? WHERE id = ?", (status, clip_id))
            conn.commit()
    except Exception:
        logger.exception(f"Erreur lors de la mise à jour du statut du clip {clip_id} vers {status}")


def _cleanup_files(paths: list[Path]) -> None:
    """Supprime proprement les fichiers de la liste pour économiser de l'espace."""
    for path in paths:
        if path and path.exists():
            try:
                if path.is_file():
                    path.unlink()
                elif path.is_dir():
                    shutil.rmtree(path)
            except Exception as e:
                logger.warning(f"Impossible de supprimer le fichier temporaire {path} : {e}")
