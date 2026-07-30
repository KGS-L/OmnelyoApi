"""
Orchestration du pipeline complet + calcul des créneaux de publication.
"""
from datetime import datetime


def get_next_available_slot() -> datetime:
    """
    Regarde la DB pour trouver le prochain créneau libre parmi
    config.PUBLISH_SLOTS, en respectant config.MAX_CLIPS_PER_DAY.
    """
    raise NotImplementedError


def process_source_video(source_video_id: int) -> None:
    """
    Pipeline complet pour une vidéo source :
    download -> scene_detect -> cut -> storytime -> tts -> overlay
    -> upload R2 -> schedule sur YouTube -> notif Telegram
    """
    raise NotImplementedError
