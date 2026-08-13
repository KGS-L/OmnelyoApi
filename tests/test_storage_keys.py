"""Tests des clés de stockage isolées par tenant et exécution."""
import unittest
import uuid

from core.storage_keys import (
    belongs_to_workspace,
    job_clip_key,
    job_rendered_key,
    job_source_key,
    upload_source_key,
)


class StorageKeyTests(unittest.TestCase):
    def setUp(self):
        self.workspace_id = uuid.uuid4()
        self.job_id = uuid.uuid4()
        self.video_id = uuid.uuid4()

    def test_pipeline_artifacts_are_scoped_to_job(self):
        prefix = f"workspaces/{self.workspace_id}/jobs/{self.job_id}/"
        self.assertTrue(job_source_key(self.workspace_id, self.job_id, ".mov").startswith(prefix))
        self.assertTrue(job_clip_key(self.workspace_id, self.job_id, 2).startswith(prefix))
        self.assertTrue(job_rendered_key(self.workspace_id, self.job_id).startswith(prefix))

    def test_direct_upload_is_scoped_to_video(self):
        key = upload_source_key(self.workspace_id, self.video_id, ".mp4")
        self.assertEqual(
            key,
            f"workspaces/{self.workspace_id}/videos/{self.video_id}/source.mp4",
        )

    def test_invalid_suffix_and_sequence_are_rejected(self):
        with self.assertRaises(ValueError):
            upload_source_key(self.workspace_id, self.video_id, "../../secret")
        with self.assertRaises(ValueError):
            job_clip_key(self.workspace_id, self.job_id, 0)

    def test_workspace_ownership_is_strict(self):
        key = job_rendered_key(self.workspace_id, self.job_id)
        self.assertTrue(belongs_to_workspace(key, self.workspace_id))
        self.assertFalse(belongs_to_workspace(key, uuid.uuid4()))


if __name__ == "__main__":
    unittest.main()
