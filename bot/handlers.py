"""
Point d'entrée de Robot Short Yt.
Initialise la DB, lance le serveur OAuth, démarre le bot Telegram.
"""
import asyncio
import logging
from pathlib import Path

import config
from db.database import init_db
from bot.telegram_bot import build_bot, run_bot
from bot.oauth_server import start_in_background, set_on_connected_callback
from bot.handlers import _on_youtube_connected


def setup_logging() -> None:
    """Configure les logs."""
    config.LOGS_DIR.mkdir(parents=True, exist_ok=True)
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        handlers=[
            logging.FileHandler(config.LOGS_DIR / "bot.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


async def main() -> None:
    """Fonction principale async."""
    setup_logging()
    logger = logging.getLogger(__name__)
    logger.info("=== Démarrage Robot Short YT ===")
    
    # Créer les dossiers
    for d in [config.TMP_DIR, config.PROCESSED_DIR, config.LOGS_DIR, config.YOUTUBE_TOKEN_FILE.parent]:
        d.mkdir(parents=True, exist_ok=True)
    
    # Base de données
    init_db()
    
    # Démarrer serveur OAuth avec référence au loop pour les callbacks async
    loop = asyncio.get_running_loop()
    set_on_connected_callback(_on_youtube_connected, loop=loop)
    start_in_background()
    logger.info("Serveur OAuth démarré")
    
    # Construire et lancer le bot
    app = build_bot()
    logger.info("Bot Telegram prêt")
    
    # TODO: démarrer APScheduler ici si besoin
    
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    
    # Garder le programme en vie
    try:
        await asyncio.Event().wait()
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()


if __name__ == "__main__":
    asyncio.run(main())