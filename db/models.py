"""
Dataclasses représentant les entités de la DB (mapping léger, pas d'ORM lourd).
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class SourceVideo:
    id: Optional[int]
    source_url: str
    local_path: Optional[str]
    status: str  # pending | downloading | cutting | done | failed


@dataclass
class Clip:
    id: Optional[int]
    source_video_id: int
    sequence_order: int
    local_path: Optional[str]
    r2_url: Optional[str]
    duration_sec: Optional[float]
    story_text: Optional[str]
    tts_audio_path: Optional[str]
    youtube_video_id: Optional[str]
    youtube_title: Optional[str]
    scheduled_publish_at: Optional[str]
    status: str  # draft | rendering | uploaded | scheduled | published | failed
