"""Boucle d'exécution sûre des jobs PostgreSQL."""
import logging
import os
import signal
import socket
import uuid
from datetime import datetime, timezone
from threading import Event, Thread

from redis import Redis
from redis.exceptions import RedisError

from api.config import APISettings
from api.database import SessionLocal
from workers.job_state import (
    claim_next_job,
    complete_job,
    defer_job,
    fail_job,
    heartbeat_job,
    recover_stale_jobs,
)
from workers.registry import HandlerRegistry, JobDeferred
from workers.signals import WAKEUP_CHANNEL

logger = logging.getLogger(__name__)


class WorkerRunner:
    def __init__(
        self,
        settings: APISettings,
        registry: HandlerRegistry,
        redis: Redis,
        worker_id: str | None = None,
    ) -> None:
        self.settings = settings
        self.registry = registry
        self.redis = redis
        self.worker_id = worker_id or (
            f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
        )
        self.stop_event = Event()
        self._last_recovery = datetime.min.replace(tzinfo=timezone.utc)

    def run_forever(self) -> None:
        self._install_signal_handlers()
        if not self.registry.job_types:
            logger.warning(
                "Worker démarré sans handler : aucun job ne sera revendiqué."
            )
        pubsub = self.redis.pubsub(ignore_subscribe_messages=True)
        try:
            pubsub.subscribe(WAKEUP_CHANNEL)
        except RedisError:
            logger.warning("Abonnement Redis indisponible ; mode polling actif.", exc_info=True)
            pubsub = None

        logger.info("Worker %s démarré", self.worker_id)
        while not self.stop_event.is_set():
            self._recover_if_due()
            processed = self.run_once()
            if not processed:
                self._wait_for_work(pubsub)
        if pubsub is not None:
            pubsub.close()
        logger.info("Worker %s arrêté", self.worker_id)

    def run_once(self) -> bool:
        with SessionLocal() as db:
            job = claim_next_job(db, self.worker_id, self.registry.job_types)
        if job is None:
            return False
        handler = self.registry.get(job.type)
        if handler is None:
            logger.error("Job %s revendiqué sans handler", job.id)
            return False

        def heartbeat(progress: int | None = None) -> bool:
            with SessionLocal() as heartbeat_db:
                return heartbeat_job(
                    heartbeat_db, job.id, self.worker_id, progress=progress
                )

        heartbeat_stop = Event()
        heartbeat_thread = Thread(
            target=self._heartbeat_loop,
            args=(heartbeat, heartbeat_stop),
            daemon=True,
            name=f"heartbeat-{job.id}",
        )
        heartbeat_thread.start()
        try:
            result = handler(job, heartbeat)
        except JobDeferred as exc:
            logger.info("Job %s différé : %s", job.id, exc)
            with SessionLocal() as deferred_db:
                defer_job(
                    deferred_db,
                    job.id,
                    self.worker_id,
                    str(exc),
                    exc.delay_seconds,
                )
        except Exception as exc:
            logger.exception("Échec du job %s", job.id)
            with SessionLocal() as failure_db:
                fail_job(
                    failure_db,
                    job.id,
                    self.worker_id,
                    str(exc),
                    self.settings.worker_retry_delay_seconds,
                )
        else:
            with SessionLocal() as completion_db:
                complete_job(completion_db, job.id, self.worker_id, result)
        finally:
            heartbeat_stop.set()
            heartbeat_thread.join(timeout=2)
        return True

    def stop(self, *_args) -> None:
        self.stop_event.set()

    def _recover_if_due(self) -> None:
        now = datetime.now(timezone.utc)
        elapsed = (now - self._last_recovery).total_seconds()
        if elapsed < self.settings.worker_recovery_interval_seconds:
            return
        with SessionLocal() as db:
            recovered = recover_stale_jobs(
                db, self.settings.worker_stale_after_seconds
            )
        if recovered:
            logger.warning("%s job(s) abandonné(s) récupéré(s)", recovered)
        self._last_recovery = now

    def _wait_for_work(self, pubsub) -> None:
        timeout = self.settings.worker_poll_interval_seconds
        if pubsub is None:
            self.stop_event.wait(timeout)
            return
        try:
            pubsub.get_message(timeout=timeout)
        except RedisError:
            logger.warning("Réveil Redis indisponible ; poursuite par polling.", exc_info=True)
            self.stop_event.wait(timeout)

    def _install_signal_handlers(self) -> None:
        signal.signal(signal.SIGTERM, self.stop)
        signal.signal(signal.SIGINT, self.stop)

    def _heartbeat_loop(self, heartbeat, stop_event: Event) -> None:
        interval = self.settings.worker_heartbeat_interval_seconds
        while not stop_event.wait(interval):
            try:
                if not heartbeat():
                    logger.warning("Lease perdue pendant le heartbeat du worker %s", self.worker_id)
                    return
            except Exception:
                logger.exception("Échec du heartbeat du worker %s", self.worker_id)
