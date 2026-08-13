"""Registre explicite des handlers de jobs supportés par un worker."""
from collections.abc import Callable
from typing import Any

from api.models import Job, JobType

JobHandler = Callable[[Job, Callable[[], bool]], dict[str, Any] | None]


class JobDeferred(Exception):
    """Demande au runner de remettre un job en attente sans compter un échec."""

    def __init__(self, reason: str, delay_seconds: int = 30):
        super().__init__(reason)
        self.delay_seconds = delay_seconds


class HandlerRegistry:
    def __init__(self) -> None:
        self._handlers: dict[JobType, JobHandler] = {}

    @property
    def job_types(self) -> frozenset[JobType]:
        return frozenset(self._handlers)

    def register(self, job_type: JobType, handler: JobHandler) -> None:
        if job_type in self._handlers:
            raise ValueError(f"Un handler est déjà enregistré pour {job_type.value}.")
        self._handlers[job_type] = handler

    def get(self, job_type: JobType) -> JobHandler | None:
        return self._handlers.get(job_type)


registry = HandlerRegistry()
