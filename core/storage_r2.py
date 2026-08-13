"""
Upload/archivage des clips finaux sur Cloudflare R2 (compatible API S3 via boto3).
"""
import logging
import shutil
from pathlib import Path

import config

logger = logging.getLogger(__name__)


def _validate_remote_key(remote_key: str) -> str:
    normalized = remote_key.strip().lstrip("/")
    if not normalized or ".." in normalized.split("/"):
        raise ValueError("Clé de stockage R2 invalide.")
    return normalized


def _client():
    import boto3

    return boto3.client(
        service_name="s3",
        endpoint_url=config.R2_ENDPOINT_URL,
        aws_access_key_id=config.R2_ACCESS_KEY_ID,
        aws_secret_access_key=config.R2_SECRET_ACCESS_KEY,
        region_name="auto",
    )


def upload_to_r2(local_path: Path, remote_key: str) -> str:
    """
    Upload le fichier local vers R2 sous `remote_key`.
    Retourne l'URL publique/accessible du fichier.
    """
    remote_key = _validate_remote_key(remote_key)
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
        s3_client = _client()
        
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


def download_from_r2(remote_key: str, destination: Path) -> Path:
    """Récupère un objet privé R2 ou son équivalent du stockage local de secours."""
    remote_key = _validate_remote_key(remote_key)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not all([config.R2_ACCESS_KEY_ID, config.R2_SECRET_ACCESS_KEY, config.R2_ENDPOINT_URL]):
        source = config.PROCESSED_DIR / remote_key
        if not source.is_file():
            raise FileNotFoundError(f"Objet local introuvable : {remote_key}")
        shutil.copy2(source, destination)
        return destination
    try:
        _client().download_file(config.R2_BUCKET_NAME, remote_key, str(destination))
    except Exception as exc:
        logger.exception("Échec du téléchargement depuis Cloudflare R2")
        raise RuntimeError(f"Échec du téléchargement R2 : {exc}") from exc
    if not destination.is_file() or destination.stat().st_size == 0:
        raise RuntimeError("R2 a produit un fichier vide ou introuvable.")
    return destination


def delete_from_r2(remote_key: str) -> None:
    """Supprime un objet privé, y compris dans le stockage local de secours."""
    remote_key = _validate_remote_key(remote_key)
    if not all([config.R2_ACCESS_KEY_ID, config.R2_SECRET_ACCESS_KEY, config.R2_ENDPOINT_URL]):
        (config.PROCESSED_DIR / remote_key).unlink(missing_ok=True)
        return
    try:
        _client().delete_object(Bucket=config.R2_BUCKET_NAME, Key=remote_key)
    except Exception as exc:
        logger.exception("Échec de suppression depuis Cloudflare R2")
        raise RuntimeError("Impossible de supprimer l'objet R2.") from exc


def create_presigned_download_url(remote_key: str, expires_in: int = 900) -> str:
    """Crée une URL GET temporaire sans rendre le bucket public."""
    remote_key = _validate_remote_key(remote_key)
    if not 60 <= expires_in <= 3600:
        raise ValueError("La durée d'une URL signée doit être comprise entre 60 et 3600 secondes.")
    if not all([config.R2_ACCESS_KEY_ID, config.R2_SECRET_ACCESS_KEY, config.R2_ENDPOINT_URL]):
        raise RuntimeError("Cloudflare R2 n'est pas configuré pour les URLs signées.")
    try:
        return _client().generate_presigned_url(
            "get_object",
            Params={"Bucket": config.R2_BUCKET_NAME, "Key": remote_key},
            ExpiresIn=expires_in,
        )
    except Exception as exc:
        logger.exception("Échec de création de l'URL R2 signée")
        raise RuntimeError("Impossible de créer l'URL de téléchargement temporaire.") from exc
