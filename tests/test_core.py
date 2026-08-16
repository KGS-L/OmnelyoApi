"""Tests unitaires des règles critiques sans appel aux services externes."""
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

import config
from core.llm_provider import get_llm_settings
from core.scene_detect import merge_scenes_to_clip_ranges
from bot.upload_helpers import parse_upload_caption


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


if __name__ == "__main__":
    unittest.main()
