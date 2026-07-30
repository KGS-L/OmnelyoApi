"""
Point d'entrée de Robot Short Yt.
Initialise la DB, lance le bot Telegram, démarre le watchdog planifié.
"""
from db.database import init_db
from bot.telegram_bot import run_bot
from bot.oauth_server import start_in_background as start_oauth_server


def main() -> None:
    init_db()
    start_oauth_server()  # écoute /oauth2callback en arrière-plan (derrière Caddy/nginx)
    # TODO: démarrer le scheduler APScheduler pour le watchdog quotidien
    run_bot()


if __name__ == "__main__":
    main()
