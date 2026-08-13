"""Détection, découpage et conversion verticale des clips d'une source."""
import mimetypes
import shutil
import uuid
from pathlib import Path

from sqlalchemy import select

from api.database import SessionLocal
from api.models import Job, JobType, Video, VideoKind, VideoStatus
from workers.registry import registry
from core.storage_keys import job_clip_key


def process_video(job: Job, heartbeat) -> dict:
    from core.scene_detect import detect_scenes, merge_scenes_to_clip_ranges
    from core.storage_r2 import download_from_r2, upload_to_r2
    from core.video_cutter import cut_clip
    from core.video_processor import process_for_short
    import config

    if job.video_id is None:
        raise ValueError("Le job PROCESS requiert une vidéo source.")
    source = _load_source(job)
    work_dir = (
        config.TMP_DIR
        / "workspaces"
        / str(job.workspace_id)
        / "jobs"
        / str(job.id)
    )
    source_path = work_dir / "source" / Path(source.storage_key).name
    try:
        _require_lease(heartbeat, "avant la récupération de la source", 5)
        download_from_r2(source.storage_key, source_path)
        _require_lease(heartbeat, "avant la détection des scènes", 15)
        scenes = detect_scenes(source_path)
        ranges = merge_scenes_to_clip_ranges(
            scenes, config.CLIP_MIN_DURATION_SEC, config.CLIP_MAX_DURATION_SEC
        )
        if not ranges:
            raise RuntimeError("Aucune plage de clip n'a été générée.")
        clip_ids: list[str] = []
        for sequence, (start_sec, end_sec) in enumerate(ranges, start=1):
            progress = 20 + int(70 * (sequence - 1) / len(ranges))
            _require_lease(heartbeat, f"avant le clip {sequence}", progress)
            clip = _existing_ready_clip(source.id, sequence)
            if clip is None:
                clip = _render_clip(
                    job,
                    source,
                    source_path,
                    work_dir,
                    sequence,
                    start_sec,
                    end_sec,
                    cut_clip,
                    process_for_short,
                    upload_to_r2,
                )
            clip_ids.append(str(clip.id))
        with SessionLocal() as db:
            persisted = db.get(Video, source.id)
            persisted.status = VideoStatus.READY
            persisted.error_message = None
            db.commit()
        return {
            "source_video_id": str(source.id),
            "clip_ids": clip_ids,
            "clip_count": len(clip_ids),
        }
    except Exception as exc:
        with SessionLocal() as db:
            persisted = db.get(Video, source.id)
            if persisted is not None:
                persisted.status = VideoStatus.FAILED
                persisted.error_message = str(exc)[:2000]
                db.commit()
        raise
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def _load_source(job: Job) -> Video:
    with SessionLocal() as db:
        source = db.scalar(
            select(Video).where(
                Video.id == job.video_id,
                Video.workspace_id == job.workspace_id,
                Video.kind == VideoKind.SOURCE,
            )
        )
        if source is None:
            raise ValueError("La vidéo source est introuvable.")
        if not source.storage_key:
            raise ValueError("La vidéo source n'est pas encore archivée.")
        source.status = VideoStatus.PROCESSING
        source.error_message = None
        db.commit()
        db.expunge(source)
        return source


def _existing_ready_clip(source_id: uuid.UUID, sequence: int) -> Video | None:
    with SessionLocal() as db:
        clip = db.scalar(
            select(Video).where(
                Video.parent_video_id == source_id,
                Video.sequence_order == sequence,
                Video.status == VideoStatus.READY,
            )
        )
        if clip is not None:
            db.expunge(clip)
        return clip


def _render_clip(
    job,
    source,
    source_path,
    work_dir,
    sequence,
    start_sec,
    end_sec,
    cut_clip,
    process_for_short,
    upload_to_r2,
) -> Video:
    raw_path = work_dir / "clips" / f"{sequence:03d}_raw.mp4"
    final_path = work_dir / "clips" / f"{sequence:03d}_short.mp4"
    cut_clip(source_path, start_sec, end_sec, raw_path, remove_audio=True)
    process_for_short(raw_path, final_path)
    storage_key = job_clip_key(job.workspace_id, job.id, sequence)
    upload_to_r2(final_path, storage_key)
    duration = end_sec - start_sec
    with SessionLocal() as db:
        clip = db.scalar(
            select(Video).where(
                Video.parent_video_id == source.id,
                Video.sequence_order == sequence,
            )
        )
        if clip is None:
            clip = Video(
                workspace_id=job.workspace_id,
                parent_video_id=source.id,
                kind=VideoKind.CLIP,
                sequence_order=sequence,
            )
            db.add(clip)
        clip.title = f"{source.title or 'Clip'} — Partie {sequence}"
        clip.storage_key = storage_key
        clip.mime_type = mimetypes.guess_type(final_path.name)[0] or "video/mp4"
        clip.duration_seconds = duration
        clip.status = VideoStatus.READY
        clip.error_message = None
        db.commit()
        db.refresh(clip)
        db.expunge(clip)
        return clip


def _require_lease(heartbeat, stage: str, progress: int | None = None) -> None:
    if not heartbeat(progress):
        raise RuntimeError(f"Lease du job perdue {stage}.")


registry.register(JobType.PROCESS, process_video)
