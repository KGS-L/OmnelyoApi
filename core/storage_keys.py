"""Construction centralisée des clés d'objets privées du SaaS."""
import uuid
from pathlib import PurePosixPath


def upload_source_key(workspace_id: uuid.UUID, video_id: uuid.UUID, suffix: str) -> str:
    return f"workspaces/{workspace_id}/videos/{video_id}/source{_suffix(suffix)}"


def job_source_key(workspace_id: uuid.UUID, job_id: uuid.UUID, suffix: str) -> str:
    return f"workspaces/{workspace_id}/jobs/{job_id}/source/input{_suffix(suffix)}"


def job_clip_key(workspace_id: uuid.UUID, job_id: uuid.UUID, sequence: int) -> str:
    if sequence <= 0:
        raise ValueError("La séquence d'un clip doit être positive.")
    return f"workspaces/{workspace_id}/jobs/{job_id}/clips/{sequence:03d}.mp4"


def job_rendered_key(workspace_id: uuid.UUID, job_id: uuid.UUID) -> str:
    return f"workspaces/{workspace_id}/jobs/{job_id}/rendered/output.mp4"


def belongs_to_workspace(key: str, workspace_id: uuid.UUID) -> bool:
    return key.startswith(f"workspaces/{workspace_id}/") and ".." not in key.split("/")


def _suffix(value: str) -> str:
    suffix = PurePosixPath(f"file{value.lower()}").suffix
    if suffix not in {".mp4", ".mov", ".webm"}:
        raise ValueError("Extension vidéo de stockage non prise en charge.")
    return suffix
