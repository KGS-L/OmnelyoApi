"""Signal Redis facultatif accélérant la prise en charge des jobs."""
import logging

from redis import Redis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)
WAKEUP_CHANNEL = "shortpilot:jobs:wakeup"


def notify_workers(redis: Redis, job_id: str) -> bool:
    try:
        redis.publish(WAKEUP_CHANNEL, job_id)
        return True
    except RedisError:
        logger.warning(
            "Signal Redis indisponible ; le polling PostgreSQL prendra le relais.",
            exc_info=True,
        )
        return False
