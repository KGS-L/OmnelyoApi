"""Chargement explicite des handlers disponibles dans ce processus."""
from workers.handlers import ingest  # noqa: F401
from workers.handlers import process  # noqa: F401
from workers.handlers import render  # noqa: F401
