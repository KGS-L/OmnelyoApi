"""
Initialisation du bot Telegram Robot Short Yt (polling).
"""
from telegram.ext import Application
import config
from bot import handlers


def build_bot() -> Application:
    """Construit l'application Telegram avec tous les handlers enregistrés."""
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).post_init(handlers.post_init).build()
    handlers.register_handlers(app)
    return app


def run_bot() -> None:
    app = build_bot()
    app.run_polling()
