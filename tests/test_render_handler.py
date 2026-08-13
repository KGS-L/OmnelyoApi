"""Tests du contrat idempotent du handler RENDER."""
import unittest
from types import SimpleNamespace

from api.models import JobType
from workers.handlers.render import DEFAULT_THEME, _result, _theme
from workers.registry import registry


class RenderHandlerTests(unittest.TestCase):
    def test_render_handler_is_registered(self):
        self.assertIsNotNone(registry.get(JobType.RENDER))

    def test_default_theme_is_used_for_invalid_payload(self):
        self.assertEqual(_theme(SimpleNamespace(payload={})), DEFAULT_THEME)
        self.assertEqual(_theme(SimpleNamespace(payload={"theme": 42})), DEFAULT_THEME)

    def test_theme_is_trimmed_and_bounded(self):
        theme = "  " + ("x" * 600) + "  "
        self.assertEqual(len(_theme(SimpleNamespace(payload={"theme": theme}))), 500)

    def test_result_exposes_persisted_render(self):
        clip = SimpleNamespace(
            id="clip-id",
            rendered_storage_key="workspaces/ws/rendered/001.mp4",
            narration_text="Une histoire",
        )
        self.assertEqual(_result(clip)["narration_text"], "Une histoire")


if __name__ == "__main__":
    unittest.main()
