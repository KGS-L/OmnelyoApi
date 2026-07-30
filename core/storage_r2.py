"""
Upload/archivage des clips finaux sur Cloudflare R2 (compatible API S3 via boto3).
"""
import logging
import shutil
from pathlib import Path
import boto3

import config

logger = logging.getLogger(__name__)


def upload_to_r2(local_path: Path, remote_key: str) -> str:
    """
    Upload le fichier local vers R2 sous `remote_key`.
    Retourne l'URL publique/accessible du fichier.
    """
    # Si R2 n'est pas configuré, on utilise une copie locale en fallback
    if not all([config.R2_ACCESS_KEY_ID, config.R2_SECRET_ACCESS_KEY, config.R2_ENDPOINT_URL]):
        fallback_path = config.PROCESSED_DIR / remote_key
        fallback_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(local_path, fallback_path)
        logger.warning(
            "Les identifiants Cloudflare R2 sont manquants dans le fichier .env. "
            f"Sauvegarde en local par défaut dans : {fallback_path}"
        )
        return fallback_path.as_uri()

    logger.info(f"Téléversement de {local_path.name} vers R2 ({remote_key})...")
    
    try:
        s3_client = boto3.client(
            service_name="s3",
            endpoint_url=config.R2_ENDPOINT_URL,
            aws_access_key_id=config.R2_ACCESS_KEY_ID,
            aws_secret_access_key=config.R2_SECRET_ACCESS_KEY,
            region_name="auto"
        )
        
        # Déterminer le Content-Type pour le navigateur
        content_type = "binary/octet-stream"
        ext = local_path.suffix.lower()
        if ext == ".mp4":
            content_type = "video/mp4"
        elif ext in [".jpg", ".jpeg"]:
            content_type = "image/jpeg"
        elif ext == ".png":
            content_type = "image/png"
        elif ext == ".mp3":
            content_type = "audio/mpeg"

        s3_client.upload_file(
            Filename=str(local_path),
            Bucket=config.R2_BUCKET_NAME,
            Key=remote_key,
            ExtraArgs={"ContentType": content_type}
        )
        
        # URL d'accès direct R2 (à adapter si un domaine personnalisé est configuré sur R2)
        public_url = f"{config.R2_ENDPOINT_URL.rstrip('/')}/{config.R2_BUCKET_NAME}/{remote_key}"
        logger.info(f"Fichier téléversé sur R2. URL publique de secours : {public_url}")
        return public_url
        
    except Exception as e:
        logger.exception("Échec du téléversement sur Cloudflare R2")
        raise RuntimeError(f"Échec R2 : {e}") from e
