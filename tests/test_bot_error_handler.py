"""Tests du handler d'erreurs du bot Telegram."""
import asyncio
import unittest
from types import SimpleNamespace

from telegram.error import Conflict

from bot import handlers


def _context(error: Exception) -> SimpleNamespace:
    return SimpleNamespace(error=error)


class BotErrorHandlerTests(unittest.TestCase):
    def setUp(self):
        handlers._conflit_getupdates_journalise = False

    def test_conflict_logs_actionable_message_once(self):
        with self.assertLogs("bot.handlers", level="ERROR") as captured:
            asyncio.run(
                handlers.on_error(None, _context(Conflict("terminated by other request")))
            )
            asyncio.run(
                handlers.on_error(None, _context(Conflict("terminated by other request")))
            )
        conflits = [
            record.getMessage()
            for record in captured.records
            if "Conflit getUpdates" in record.getMessage()
        ]
        self.assertEqual(len(conflits), 1)
        self.assertIn("@BotFather", conflits[0])
        self.assertIn("VPS", conflits[0])

    def test_conflict_flag_is_resettable_for_next_run(self):
        with self.assertLogs("bot.handlers", level="ERROR"):
            asyncio.run(
                handlers.on_error(None, _context(Conflict("terminated by other request")))
            )
        handlers._conflit_getupdates_journalise = False
        with self.assertLogs("bot.handlers", level="ERROR") as second:
            asyncio.run(
                handlers.on_error(None, _context(Conflict("terminated by other request")))
            )
        self.assertTrue(
            any("Conflit getUpdates" in r.getMessage() for r in second.records)
        )

    def test_other_errors_are_logged_with_exception_context(self):
        error = RuntimeError("boom")
        with self.assertLogs("bot.handlers", level="ERROR") as captured:
            asyncio.run(handlers.on_error(SimpleNamespace(update_id=1), _context(error)))
        self.assertEqual(len(captured.records), 1)
        self.assertIs(captured.records[0].exc_info[1], error)

    def test_error_handler_is_registered(self):
        # Sans instance réelle d'Application, on vérifie l'enregistrement via
        # le patch du point d'entrée utilisé par register_handlers.
        from unittest.mock import MagicMock

        app = MagicMock()
        previous = handlers._application
        try:
            handlers.register_handlers(app)
        finally:
            handlers._application = previous
        app.add_error_handler.assert_called_once_with(handlers.on_error)


if __name__ == "__main__":
    unittest.main()
