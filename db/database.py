"""
Connexion SQLite + exécution du schéma + fonctions de requêtes de base.
"""
import sqlite3
from pathlib import Path
import config


def get_connection() -> sqlite3.Connection:
    """Ouvre (et crée si besoin) la connexion à la DB SQLite."""
    conn = sqlite3.connect(config.DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Exécute schema.sql pour créer les tables si elles n'existent pas."""
    schema_path = Path(__file__).parent / "schema.sql"
    with get_connection() as conn:
        conn.executescript(schema_path.read_text())
