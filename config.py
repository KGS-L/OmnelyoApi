"""
Config centrale du projet Robot Short Yt.
Charge les variables d'environnement (.env) et les expose comme constantes typées.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

# Créer les répertoires de base au chargement
for _dir in [BASE_DIR / "credentials", BASE_DIR / "db", BASE_DIR / "storage" / "tmp", 
             BASE_DIR / "storage" / "processed", BASE_DIR / "logs"]:
    _dir.mkdir(parents=True, exist_ok=True)

# --- Telegram ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_ADMIN_CHAT_ID = os.getenv("TELEGRAM_ADMIN_CHAT_ID", "")

# --- YouTube ---
YOUTUBE_CLIENT_SECRETS_FILE = BASE_DIR / os.getenv(
    "YOUTUBE_CLIENT_SECRETS_FILE", "credentials/client_secret.json"
)
YOUTUBE_TOKEN_FILE = BASE_DIR / os.getenv("YOUTUBE_TOKEN_FILE", "credentials/token.json")

YOUTUBE_REDIRECT_URI = os.getenv("YOUTUBE_REDIRECT_URI", "")
OAUTH_CALLBACK_PORT = int(os.getenv("OAUTH_CALLBACK_PORT", 8420))

# --- Cloudflare R2 ---
R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID", "")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID", "")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY", "")
R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME", "robot-short-yt")
R2_ENDPOINT_URL = os.getenv("R2_ENDPOINT_URL", "")

# --- LLM ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL")

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")

# --- Scheduling ---
PUBLISH_SLOTS = os.getenv("PUBLISH_SLOTS", "12:00,17:00,20:00").split(",")
MAX_CLIPS_PER_DAY = int(os.getenv("MAX_CLIPS_PER_DAY", 3))
CLIP_MIN_DURATION_SEC = int(os.getenv("CLIP_MIN_DURATION_SEC", 60))
CLIP_MAX_DURATION_SEC = int(os.getenv("CLIP_MAX_DURATION_SEC", 150))
TIMEZONE = os.getenv("TIMEZONE", "Africa/Ouagadougou")

# --- DB ---
DATABASE_PATH = BASE_DIR / os.getenv("DATABASE_PATH", "db/robot_short_yt.sqlite3")

# --- Storage locale ---
TMP_DIR = BASE_DIR / "storage" / "tmp"
PROCESSED_DIR = BASE_DIR / "storage" / "processed"
LOGS_DIR = BASE_DIR / "logs"