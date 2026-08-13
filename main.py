"""
Point d'entrée de ShortPilot.
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
    # httpx journalise autrement les URLs Telegram complètes, lesquelles
    # contiennent le token du bot dans leur chemin.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def main() -> None:
    setup_logging()
    logger = logging.getLogger(__name__)
    logger.info("=== Démarrage ShortPilot ===")
    
    # Initialisation base de données
    init_db()

    from scheduler.job_queue import start_worker, stop_worker
    start_worker()
    
    # Démarrage serveur OAuth en arrière-plan
    start_oauth_server()
    logger.info("Serveur OAuth démarré")
    
    # Démarrer le planificateur de tâches pour le watchdog
    from scheduler.watchdog import start_scheduler
    start_scheduler()
    
    # Lancer le bot Telegram (bloquant, en dernier)
    try:
        start_bot()
    finally:
        stop_worker()


if __name__ == "__main__":
    main()
