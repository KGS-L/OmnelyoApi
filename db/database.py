"""
Connexion SQLite + exécution du schéma + fonctions de requêtes de base.
"""
import sqlite3
from pathlib import Path
import config


def get_connection() -> sqlite3.Connection:
    """Ouvre (et crée si besoin) la connexion à la DB SQLite."""
    config.DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DATABASE_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def init_db() -> None:
    """Exécute schema.sql pour créer les tables si elles n'existent pas."""
    schema_path = Path(__file__).parent / "schema.sql"
    with get_connection() as conn:
        conn.executescript(schema_path.read_text())
        _migrate_source_video_owner(conn)


def _migrate_source_video_owner(conn: sqlite3.Connection) -> None:
    """Ajoute les colonnes multi-utilisateur aux bases créées avant cette version."""
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(source_videos)")}
    if "telegram_user_id" not in columns:
        conn.execute("ALTER TABLE source_videos ADD COLUMN telegram_user_id INTEGER")
    if "telegram_chat_id" not in columns:
        conn.execute("ALTER TABLE source_videos ADD COLUMN telegram_chat_id INTEGER")
    if "source_type" not in columns:
        conn.execute("ALTER TABLE source_videos ADD COLUMN source_type TEXT NOT NULL DEFAULT 'url'")
    if "requested_publish_at" not in columns:
        conn.execute("ALTER TABLE source_videos ADD COLUMN requested_publish_at TEXT")
    if "requested_title" not in columns:
        conn.execute("ALTER TABLE source_videos ADD COLUMN requested_title TEXT")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_source_videos_user "
        "ON source_videos(telegram_user_id)"
    )
