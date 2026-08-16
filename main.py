"""
Point d'entrée du bot Telegram ShortPilot.
Lance le serveur OAuth en arrière-plan puis le bot (bloquant).
Les traitements métier sont exécutés par le worker PostgreSQL.
"""
import logging

import config
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

    # Démarrage serveur OAuth en arrière-plan
    start_oauth_server()
    logger.info("Serveur OAuth démarré")

    # Lancer le bot Telegram (bloquant, en dernier)
    start_bot()


if __name__ == "__main__":
    main()
