"""Tests unitaires des règles critiques sans appel aux services externes."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

import config
from core.llm_provider import get_llm_settings
from core.scene_detect import merge_scenes_to_clip_ranges
from bot.upload_helpers import parse_upload_caption
from db.database import init_db
from scheduler.job_queue import cancel_job, enqueue_job, list_user_jobs
from billing.providers.manual import ManualPaymentProvider
from billing.repository import BillingRepository
from billing.service import BillingService


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


class UploadCaptionTests(unittest.TestCase):
    def test_auto_schedule_and_title(self) -> None:
        request = parse_upload_caption("auto | Une superbe vidéo")
        self.assertIsNone(request.publish_at)
        self.assertEqual(request.title, "Une superbe vidéo")

    def test_manual_schedule_uses_configured_timezone(self) -> None:
        now = datetime(2026, 8, 13, 10, 0, tzinfo=ZoneInfo(config.TIMEZONE))
        request = parse_upload_caption("2026-08-14 17:30 | Episode 1", now=now)
        self.assertEqual(request.publish_at.hour, 17)
        self.assertEqual(request.title, "Episode 1")

    def test_invalid_caption_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            parse_upload_caption("demain soir | Episode 1")


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
                self.assertIn("source_type", columns)
                self.assertIn("requested_publish_at", columns)
                self.assertIn("requested_title", columns)
                with sqlite3.connect(database_path) as conn:
                    tables = {
                        row[0] for row in conn.execute(
                            "SELECT name FROM sqlite_master WHERE type = 'table'"
                        )
                    }
                self.assertIn("jobs", tables)
            finally:
                config.DATABASE_PATH = old_path


class JobQueueTests(unittest.TestCase):
    def setUp(self) -> None:
        self.old_path = config.DATABASE_PATH
        self.temp_dir = tempfile.TemporaryDirectory()
        config.DATABASE_PATH = Path(self.temp_dir.name) / "queue.sqlite3"
        init_db()

    def tearDown(self) -> None:
        config.DATABASE_PATH = self.old_path
        self.temp_dir.cleanup()

    def test_enqueue_list_and_cancel_owned_job(self) -> None:
        with sqlite3.connect(config.DATABASE_PATH) as conn:
            cursor = conn.execute(
                "INSERT INTO source_videos "
                "(telegram_user_id, telegram_chat_id, source_url) VALUES (42, 42, 'https://example.com')"
            )
            source_id = cursor.lastrowid
        job_id = enqueue_job(source_id, "process_url")
        jobs = list_user_jobs(42)
        self.assertEqual(jobs[0]["id"], job_id)
        self.assertTrue(cancel_job(job_id, 42))
        self.assertFalse(cancel_job(job_id, 42))
        self.assertEqual(list_user_jobs(42)[0]["status"], "cancelled")

    def test_user_cannot_cancel_another_users_job(self) -> None:
        with sqlite3.connect(config.DATABASE_PATH) as conn:
            cursor = conn.execute(
                "INSERT INTO source_videos "
                "(telegram_user_id, telegram_chat_id, source_url) VALUES (42, 42, 'https://example.com')"
            )
            source_id = cursor.lastrowid
        job_id = enqueue_job(source_id, "process_url")
        self.assertFalse(cancel_job(job_id, 99))


class BillingServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.old_path = config.DATABASE_PATH
        self.temp_dir = tempfile.TemporaryDirectory()
        config.DATABASE_PATH = Path(self.temp_dir.name) / "billing.sqlite3"
        init_db()
        with sqlite3.connect(config.DATABASE_PATH) as conn:
            conn.execute(
                "INSERT INTO billing_plans "
                "(code, name, product_type, price_minor, currency, credits) "
                "VALUES ('credits_10', 'Pack 10 crédits', 'credits', 2000, 'XOF', 10)"
            )
        self.repository = BillingRepository()
        self.service = BillingService(
            self.repository,
            [ManualPaymentProvider("Paie au 70 00 00 00 par Orange Money.")],
        )

    def tearDown(self) -> None:
        config.DATABASE_PATH = self.old_path
        self.temp_dir.cleanup()

    def test_manual_checkout_and_confirmation_credit_workspace(self) -> None:
        checkout = self.service.start_checkout(
            workspace_id="workspace-1",
            plan_code="credits_10",
            customer_email="user@example.com",
            provider_name="manual",
        )
        self.assertIn(checkout.external_reference, checkout.instructions)
        self.assertTrue(
            self.service.confirm_manual_payment(
                checkout.external_reference, "ORANGE-123"
            )
        )
        self.assertEqual(self.repository.credit_balance("workspace-1"), 10)

    def test_confirmation_is_idempotent(self) -> None:
        checkout = self.service.start_checkout(
            "workspace-1", "credits_10", "user@example.com", "manual"
        )
        self.assertTrue(self.service.confirm_manual_payment(checkout.external_reference, "TX-1"))
        self.assertFalse(self.service.confirm_manual_payment(checkout.external_reference, "TX-1"))
        self.assertEqual(self.repository.credit_balance("workspace-1"), 10)

    def test_unknown_provider_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.service.start_checkout(
                "workspace-1", "credits_10", "user@example.com", "stripe"
            )

    def test_mobile_money_reference_cannot_be_reused(self) -> None:
        first = self.service.start_checkout(
            "workspace-1", "credits_10", "user@example.com", "manual"
        )
        second = self.service.start_checkout(
            "workspace-1", "credits_10", "user@example.com", "manual"
        )
        self.service.confirm_manual_payment(first.external_reference, "SAME-TX")
        with self.assertRaises(ValueError):
            self.service.confirm_manual_payment(second.external_reference, "SAME-TX")


if __name__ == "__main__":
    unittest.main()
