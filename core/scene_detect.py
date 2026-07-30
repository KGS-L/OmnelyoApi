"""
Détection des scènes (PySceneDetect) + fusion pour respecter
CLIP_MIN_DURATION_SEC / CLIP_MAX_DURATION_SEC (voir config.py).
"""
import logging
from pathlib import Path
from scenedetect import detect, ContentDetector

logger = logging.getLogger(__name__)


def detect_scenes(video_path: Path) -> list[tuple[float, float]]:
    """
    Retourne la liste brute des scènes détectées : [(start_sec, end_sec), ...]
    """
    logger.info(f"Analyse des scènes pour la vidéo : {video_path}")
    
    try:
        scene_list = detect(str(video_path), ContentDetector())
        scenes = [(start.get_seconds(), end.get_seconds()) for start, end in scene_list]
        
        if not scenes:
            # Si aucune scène n'est détectée, on considère la vidéo entière comme une scène unique
            from core.video_processor import _probe_video
            probe = _probe_video(video_path)
            duration = float(probe.get("format", {}).get("duration", 0))
            scenes = [(0.0, duration)]
            logger.info("Aucun changement de scène détecté. Utilisation de la vidéo entière.")
        else:
            logger.info(f"{len(scenes)} scènes brutes détectées.")
            
        return scenes
        
    except Exception as e:
        logger.exception("Erreur lors de la détection de scènes")
        # En cas d'erreur de la bibliothèque, on retourne au moins la vidéo complète
        try:
            from core.video_processor import _probe_video
            probe = _probe_video(video_path)
            duration = float(probe.get("format", {}).get("duration", 0))
            return [(0.0, duration)]
        except Exception:
            raise RuntimeError(f"Échec de l'analyse vidéo et de l'extraction de durée : {e}") from e


def merge_scenes_to_clip_ranges(
    scenes: list[tuple[float, float]],
    min_duration: int,
    max_duration: int,
) -> list[tuple[float, float]]:
    """
    Fusionne/découpe les scènes brutes pour obtenir des plages
    respectant min_duration <= durée <= max_duration.
    """
    if not scenes:
        return []
        
    logger.info(
        f"Fusion des scènes. Min cible: {min_duration}s, Max cible: {max_duration}s"
    )

    ranges = []
    start, end = scenes[0]
    
    for next_start, next_end in scenes[1:]:
        curr_dur = end - start
        next_dur = next_end - next_start
        
        # Si fusionner la scène suivante ne dépasse pas la durée maximale
        if curr_dur + next_dur <= max_duration:
            end = next_end
        else:
            # Enregistrer la plage courante
            ranges.append((start, end))
            start, end = next_start, next_end
            
    # Enregistrer la dernière plage
    ranges.append((start, end))
    
    # Post-traitement : découper les scènes individuelles qui dépassent le max_duration
    final_ranges = []
    for s, e in ranges:
        dur = e - s
        if dur > max_duration:
            curr_s = s
            while curr_s < e:
                curr_e = min(curr_s + max_duration, e)
                # Si la partie restante est trop courte, on l'englobe dans la plage actuelle
                if e - curr_e < min_duration and curr_e < e:
                    final_ranges.append((curr_s, e))
                    break
                else:
                    final_ranges.append((curr_s, curr_e))
                    curr_s = curr_e
        else:
            final_ranges.append((s, e))
            
    logger.info(f"Regroupement terminé. Nombre de clips prévus : {len(final_ranges)}")
    return final_ranges
