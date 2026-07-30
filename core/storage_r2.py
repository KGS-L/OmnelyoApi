"""
Upload/archivage des clips finaux sur Cloudflare R2 (compatible API S3 via boto3).
"""
from pathlib import Path


def upload_to_r2(local_path: Path, remote_key: str) -> str:
    """
    Upload le fichier local vers R2 sous `remote_key`.
    Retourne l'URL publique/accessible du fichier.
    """
    raise NotImplementedError
