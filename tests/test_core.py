"""Tests unitaires des règles critiques sans appel aux services externes."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

import config
from core.llm_provider import get_llm_settings
from core.scene_detect import merge_scenes_to_clip_ranges
from db.database import init_db


class LLMProviderTests(unittest.TestCase):
    def test_groq_uses_configured_model(self) -> None:
        old_key, old_model = config.GROQ_API_KEY, config.GROQ_MODEL
        try:
            config.GROQ_API_KEY = "test-key"
            config.GROQ_MODEL = "test-model"
            settings = get_llm_settings("groq")
            self.assertEqual(settings.model, "test-model")
            self.assertEqual(settings.base_url, "https://api.groq.com/openai/v1")
        finally:
            config.GROQ_API_KEY, config.GROQ_MODEL = old_key, old_model

    def test_unknown_provider_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            get_llm_settings("unknown")


class SceneRangeTests(unittest.TestCase):
    def test_long_scene_is_split(self) -> None:
        ranges = merge_scenes_to_clip_ranges([(0.0, 300.0)], 60, 150)
        self.assertEqual(ranges, [(0.0, 150.0), (150.0, 300.0)])


class DatabaseMigrationTests(unittest.TestCase):
    def test_existing_database_receives_owner_columns(self) -> None:
        old_path = config.DATABASE_PATH
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "test.sqlite3"
            with sqlite3.connect(database_path) as conn:
                conn.execute(
                    "CREATE TABLE source_videos "
                    "(id INTEGER PRIMARY KEY, source_url TEXT NOT NULL, status TEXT NOT NULL)"
                )
            try:
                config.DATABASE_PATH = database_path
                init_db()
                with sqlite3.connect(database_path) as conn:
                    columns = {
                        row[1] for row in conn.execute("PRAGMA table_info(source_videos)")
                    }
                self.assertIn("telegram_user_id", columns)
                self.assertIn("telegram_chat_id", columns)
            finally:
                config.DATABASE_PATH = old_path


if __name__ == "__main__":
    unittest.main()
