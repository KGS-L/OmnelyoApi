"""
Téléchargement de la vidéo source depuis un lien YouTube ou autre plateforme (yt-dlp).
"""
import logging
from pathlib import Path
import yt_dlp

logger = logging.getLogger(__name__)


def download_video(url: str, output_dir: Path) -> Path:
    """
    Télécharge la vidéo depuis `url` vers `output_dir`.
    Retourne le chemin local du fichier téléchargé.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    
    ydl_opts = {
        # Chercher de préférence du MP4 ou forcer l'assemblage en MP4
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': str(output_dir / '%(id)s.%(ext)s'),
        'merge_output_format': 'mp4',
        'quiet': True,
        'no_warnings': True,
    }
    
    logger.info(f"Début du téléchargement avec yt-dlp de l'URL : {url}")
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            path = Path(filename)
            
            # Gérer le cas où l'extension finale après fusion est .mp4 mais prepare_filename donnait autre chose
            if not path.exists():
                path = path.with_suffix('.mp4')
                
            if not path.exists():
                # Si toujours introuvable, chercher un fichier contenant l'ID de la vidéo dans le dossier
                video_id = info.get('id')
                if video_id:
                    for f in output_dir.glob(f"*{video_id}*"):
                        if f.is_file():
                            path = f
                            break
                            
            if not path.exists():
                raise FileNotFoundError(f"Fichier vidéo téléchargé introuvable pour l'URL: {url}")
                
            logger.info(f"Téléchargement terminé. Fichier enregistré sous : {path}")
            return path
            
    except Exception as e:
        logger.exception(f"Erreur de téléchargement pour l'URL {url}")
        raise RuntimeError(f"Échec du téléchargement avec yt-dlp : {e}") from e
