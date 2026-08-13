"""Point d'entrée du processus worker SaaS."""
import logging

from redis import Redis

from api.config import get_settings
from workers.registry import registry
from workers.runner import WorkerRunner


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    settings = get_settings()
    WorkerRunner(
        settings=settings,
        registry=registry,
        redis=Redis.from_url(settings.redis_url),
    ).run_forever()


if __name__ == "__main__":
    main()
