"""
Point d'entrée de Robot Short Yt.
Initialise la DB, lance le bot Telegram, démarre le watchdog planifié.
"""
import logging
from pathlib import Path

import config
from db.database import init_db
from bot.handlers import start_bot
from bot.oauth_server import start_in_background as start_oauth_server


def setup_logging() -> None:
    """Configure les logs avec rotation."""
    config.LOGS_DIR.mkdir(parents=True, exist_ok=True)
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        handlers=[
            logging.FileHandler(config.LOGS_DIR / "bot.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def main() -> None:
    setup_logging()
    logger = logging.getLogger(__name__)
    logger.info("=== Démarrage Robot Short YT ===")
    
    # Initialisation base de données
    init_db()
    
    # Démarrage serveur OAuth en arrière-plan
    start_oauth_server()
    logger.info("Serveur OAuth démarré")
    
    # TODO: démarrer APScheduler pour le watchdog quotidien
    # from core.scheduler import start_scheduler
    # start_scheduler()
    
    # Lancer le bot Telegram (bloquant, en dernier)
    start_bot()


if __name__ == "__main__":
    main()