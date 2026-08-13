"""Tests de structure des modèles métier PostgreSQL."""
import unittest

try:
    from api.models import Base, Job, Publication, TelegramConnection
except ModuleNotFoundError as exc:
    if exc.name != "sqlalchemy":
        raise
    Base = Job = Publication = TelegramConnection = None


@unittest.skipUnless(Base is not None, "SQLAlchemy n'est pas installé")
class ContentModelsTests(unittest.TestCase):
    def test_content_tables_are_registered(self):
        self.assertTrue({"channels", "videos", "jobs", "publications"}.issubset(Base.metadata.tables))

    def test_every_content_table_is_tenant_scoped(self):
        for table_name in ("channels", "videos", "jobs", "publications"):
            table = Base.metadata.tables[table_name]
            self.assertIn("workspace_id", table.c)
            self.assertTrue(table.c.workspace_id.index)

    def test_job_progress_and_retry_constraints_exist(self):
        names = {constraint.name for constraint in Job.__table__.constraints}
        self.assertTrue({"ck_jobs_progress", "ck_jobs_attempts", "ck_jobs_max_attempts"}.issubset(names))

    def test_publication_references_video_channel_and_optional_job(self):
        foreign_keys = {fk.parent.name: fk.target_fullname for fk in Publication.__table__.foreign_keys}
        self.assertEqual(foreign_keys["video_id"], "videos.id")
        self.assertEqual(foreign_keys["channel_id"], "channels.id")
        self.assertEqual(foreign_keys["job_id"], "jobs.id")
        self.assertTrue(Publication.__table__.c.job_id.nullable)

    def test_telegram_connection_is_tenant_scoped_and_unique(self):
        table = TelegramConnection.__table__
        self.assertIn("workspace_id", table.c)
        self.assertTrue(table.c.telegram_user_id.unique or table.c.telegram_user_id.index)

    def test_video_clips_are_idempotently_ordered(self):
        table = Base.metadata.tables["videos"]
        names = {constraint.name for constraint in table.constraints}
        self.assertIn("parent_video_id", table.c)
        self.assertIn("kind", table.c)
        self.assertIn("sequence_order", table.c)
        self.assertIn("uq_videos_parent_sequence", names)
        self.assertIn("ck_videos_kind_parent", names)
        self.assertIn("rendered_storage_key", table.c)
        self.assertIn("narration_text", table.c)
        self.assertIn("rendered_at", table.c)


if __name__ == "__main__":
    unittest.main()
