"""File SQLite persistante et workers de traitement limités."""
import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass

import config
from db.database import get_connection

logger = logging.getLogger(__name__)

_stop_event = threading.Event()
_dispatcher_thread: threading.Thread | None = None
_executor: ThreadPoolExecutor | None = None
_active_futures: set[Future] = set()
_active_lock = threading.Lock()


@dataclass(frozen=True)
class Job:
    id: int
    source_video_id: int
    job_type: str


def enqueue_job(source_video_id: int, job_type: str, conn=None) -> int:
    """Ajoute un job. Une connexion peut être fournie pour une création atomique."""
    if job_type not in {"process_url", "publish_upload"}:
        raise ValueError(f"Type de job inconnu : {job_type}")
    owns_connection = conn is None
    connection = conn or get_connection()
    try:
        cursor = connection.execute(
            "INSERT INTO jobs (source_video_id, job_type, max_attempts) VALUES (?, ?, ?)",
            (source_video_id, job_type, config.JOB_MAX_ATTEMPTS),
        )
        if owns_connection:
            connection.commit()
        return cursor.lastrowid
    finally:
        if owns_connection:
            connection.close()


def list_user_jobs(user_id: int, limit: int = 10):
    with get_connection() as conn:
        return conn.execute(
            "SELECT j.id, j.job_type, j.status, j.attempts, j.error_message, "
            "j.created_at, s.requested_title, s.source_type "
            "FROM jobs j JOIN source_videos s ON s.id = j.source_video_id "
            "WHERE s.telegram_user_id = ? ORDER BY j.id DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()


def cancel_job(job_id: int, user_id: int) -> bool:
    """Annule uniquement un job encore en attente et appartenant à l'utilisateur."""
    local_path = None
    with get_connection() as conn:
        row = conn.execute(
            "SELECT s.local_path FROM jobs j JOIN source_videos s ON s.id = j.source_video_id "
            "WHERE j.id = ? AND j.status = 'queued' AND s.telegram_user_id = ?",
            (job_id, user_id),
        ).fetchone()
        local_path = row["local_path"] if row else None
        cursor = conn.execute(
            "UPDATE jobs SET status = 'cancelled', finished_at = datetime('now'), "
            "updated_at = datetime('now') WHERE id = ? AND status = 'queued' "
            "AND source_video_id IN (SELECT id FROM source_videos WHERE telegram_user_id = ?)",
            (job_id, user_id),
        )
        if cursor.rowcount:
            conn.execute(
                "UPDATE source_videos SET status = 'cancelled', local_path = NULL WHERE id = "
                "(SELECT source_video_id FROM jobs WHERE id = ?)",
                (job_id,),
            )
        conn.commit()
        cancelled = cursor.rowcount == 1
    if cancelled and local_path:
        from pathlib import Path

        Path(local_path).unlink(missing_ok=True)
    return cancelled


def start_worker() -> None:
    """Relance les jobs interrompus puis démarre le dispatcher."""
    global _dispatcher_thread, _executor
    if _dispatcher_thread and _dispatcher_thread.is_alive():
        return
    with get_connection() as conn:
        conn.execute(
            "UPDATE jobs SET status = 'queued', started_at = NULL, "
            "updated_at = datetime('now'), error_message = "
            "COALESCE(error_message, 'Interrompu par un redémarrage') "
            "WHERE status = 'running' AND attempts < max_attempts"
        )
        conn.execute(
            "UPDATE jobs SET status = 'failed', finished_at = datetime('now'), "
            "updated_at = datetime('now'), error_message = 'Nombre maximal de tentatives atteint' "
            "WHERE status IN ('running', 'queued') AND attempts >= max_attempts"
        )
        conn.commit()
    _stop_event.clear()
    _executor = ThreadPoolExecutor(
        max_workers=config.JOB_WORKER_CONCURRENCY, thread_name_prefix="video-job"
    )
    _dispatcher_thread = threading.Thread(
        target=_dispatch_loop, daemon=True, name="job-dispatcher"
    )
    _dispatcher_thread.start()
    logger.info("Worker démarré avec une concurrence de %s", config.JOB_WORKER_CONCURRENCY)


def stop_worker() -> None:
    """Arrête de prendre de nouveaux jobs et attend les jobs actifs."""
    global _dispatcher_thread, _executor
    _stop_event.set()
    if _dispatcher_thread:
        _dispatcher_thread.join(timeout=5)
    if _executor:
        _executor.shutdown(wait=True, cancel_futures=False)
    _dispatcher_thread = None
    _executor = None


def _dispatch_loop() -> None:
    while not _stop_event.is_set():
        with _active_lock:
            _active_futures.difference_update({f for f in _active_futures if f.done()})
            capacity = config.JOB_WORKER_CONCURRENCY - len(_active_futures)
        for _ in range(max(0, capacity)):
            job = _claim_next_job()
            if not job or _executor is None:
                break
            future = _executor.submit(_run_job, job)
            with _active_lock:
                _active_futures.add(future)
        _stop_event.wait(config.JOB_POLL_INTERVAL_SEC)


def _claim_next_job() -> Job | None:
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT id, source_video_id, job_type FROM jobs "
            "WHERE status = 'queued' AND attempts < max_attempts ORDER BY id LIMIT 1"
        ).fetchone()
        if not row:
            conn.commit()
            return None
        cursor = conn.execute(
            "UPDATE jobs SET status = 'running', attempts = attempts + 1, "
            "started_at = datetime('now'), updated_at = datetime('now') "
            "WHERE id = ? AND status = 'queued'",
            (row["id"],),
        )
        conn.commit()
        if cursor.rowcount != 1:
            return None
        return Job(row["id"], row["source_video_id"], row["job_type"])


def _run_job(job: Job) -> None:
    from scheduler import scheduler

    try:
        if job.job_type == "process_url":
            scheduler.process_source_video(job.source_video_id)
        else:
            scheduler.process_uploaded_short(job.source_video_id)
        with get_connection() as conn:
            source = conn.execute(
                "SELECT status, error_message FROM source_videos WHERE id = ?",
                (job.source_video_id,),
            ).fetchone()
            succeeded = source and source["status"] in {"done", "partial"}
            status = "completed" if succeeded else "failed"
            error = None if succeeded else (source["error_message"] if source else "Source absente")
            conn.execute(
                "UPDATE jobs SET status = ?, error_message = ?, "
                "finished_at = datetime('now'), updated_at = datetime('now') WHERE id = ?",
                (status, error, job.id),
            )
            conn.commit()
    except Exception as exc:
        logger.exception("Erreur non gérée du job #%s", job.id)
        with get_connection() as conn:
            conn.execute(
                "UPDATE jobs SET status = 'failed', error_message = ?, "
                "finished_at = datetime('now'), updated_at = datetime('now') WHERE id = ?",
                (str(exc)[:500], job.id),
            )
            conn.commit()
