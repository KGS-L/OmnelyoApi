"""Enrichissement d'un clip avec narration, voix et overlay visuel."""
import shutil
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from api.database import SessionLocal
from api.models import Job, JobType, Video, VideoKind, VideoStatus
from workers.registry import registry
from core.storage_keys import job_rendered_key

DEFAULT_THEME = "histoire intrigante ou fait insolite"


def render_video(job: Job, heartbeat) -> dict:
    from core.overlay import overlay_card_on_video, render_comment_card
    from core.storage_r2 import download_from_r2, upload_to_r2
    from core.storytime import generate_story
    from core.tts import generate_tts
    import config

    clip = _load_clip(job)
    if clip.rendered_storage_key and clip.narration_text:
        return _result(clip)
    work_dir = (
        config.TMP_DIR
        / "workspaces"
        / str(job.workspace_id)
        / "jobs"
        / str(job.id)
    )
    input_path = work_dir / "input" / Path(clip.storage_key).name
    audio_path = work_dir / "render" / "narration.mp3"
    card_path = work_dir / "render" / "card.png"
    output_path = work_dir / "render" / "final.mp4"
    try:
        _require_lease(heartbeat, "avant la récupération du clip", 5)
        download_from_r2(clip.storage_key, input_path)
        _require_lease(heartbeat, "avant la génération du récit", 20)
        narration = clip.narration_text or generate_story(
            _theme(job), clip.duration_seconds or 60
        )
        _persist_narration(clip.id, narration)
        _require_lease(heartbeat, "avant la synthèse vocale", 40)
        generate_tts(narration, audio_path)
        card_text = narration[:120] + ("..." if len(narration) > 120 else "")
        render_comment_card(card_text, card_path)
        _require_lease(heartbeat, "avant le rendu final", 65)
        overlay_card_on_video(
            input_path,
            card_path,
            duration_sec=8,
            output_path=output_path,
            audio_path=audio_path,
        )
        rendered_key = job_rendered_key(job.workspace_id, job.id)
        upload_to_r2(output_path, rendered_key)
        _require_lease(heartbeat, "après l'archivage du rendu", 90)
        with SessionLocal() as db:
            persisted = db.get(Video, clip.id)
            persisted.rendered_storage_key = rendered_key
            persisted.narration_text = narration
            persisted.rendered_at = datetime.now(timezone.utc)
            persisted.status = VideoStatus.READY
            persisted.error_message = None
            db.commit()
            db.refresh(persisted)
            return _result(persisted)
    except Exception as exc:
        with SessionLocal() as db:
            persisted = db.get(Video, clip.id)
            if persisted is not None:
                persisted.status = VideoStatus.FAILED
                persisted.error_message = str(exc)[:2000]
                db.commit()
        raise
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def _load_clip(job: Job) -> Video:
    if job.video_id is None:
        raise ValueError("Le job RENDER requiert un clip.")
    with SessionLocal() as db:
        clip = db.scalar(
            select(Video).where(
                Video.id == job.video_id,
                Video.workspace_id == job.workspace_id,
                Video.kind == VideoKind.CLIP,
            )
        )
        if clip is None:
            raise ValueError("Le clip à rendre est introuvable.")
        if not clip.storage_key:
            raise ValueError("Le clip n'est pas encore archivé.")
        if not (clip.rendered_storage_key and clip.narration_text):
            clip.status = VideoStatus.PROCESSING
            clip.error_message = None
        else:
            clip.status = VideoStatus.READY
        db.commit()
        db.expunge(clip)
        return clip


def _persist_narration(clip_id, narration: str) -> None:
    with SessionLocal() as db:
        clip = db.get(Video, clip_id)
        clip.narration_text = narration
        db.commit()


def _theme(job: Job) -> str:
    value = (job.payload or {}).get("theme", DEFAULT_THEME)
    if not isinstance(value, str) or not value.strip():
        return DEFAULT_THEME
    return value.strip()[:500]


def _result(clip: Video) -> dict:
    return {
        "video_id": str(clip.id),
        "rendered_storage_key": clip.rendered_storage_key,
        "narration_text": clip.narration_text,
    }


def _require_lease(heartbeat, stage: str, progress: int | None = None) -> None:
    if not heartbeat(progress):
        raise RuntimeError(f"Lease du job perdue {stage}.")


registry.register(JobType.RENDER, render_video)
