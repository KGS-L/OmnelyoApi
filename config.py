"""
Configuration centrale de ShortPilot.
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
R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME", "shortpilot")
R2_ENDPOINT_URL = os.getenv("R2_ENDPOINT_URL", "")

# --- IA générative (fournisseurs compatibles avec le SDK OpenAI) ---
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq").strip().lower()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

XAI_API_KEY = os.getenv("XAI_API_KEY", "")
XAI_MODEL = os.getenv("XAI_MODEL", "grok-3-mini")

MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")
MISTRAL_MODEL = os.getenv("MISTRAL_MODEL", "mistral-small-latest")

KIMI_API_KEY = os.getenv("KIMI_API_KEY", "")
KIMI_MODEL = os.getenv("KIMI_MODEL", "kimi-k2.5")
KIMI_BASE_URL = os.getenv("KIMI_BASE_URL", "https://api.moonshot.ai/v1")

# --- Synthèse vocale OpenAI ---
TTS_PROVIDER = os.getenv("TTS_PROVIDER", "openai").strip().lower()
OPENAI_TTS_MODEL = os.getenv("OPENAI_TTS_MODEL", "gpt-4o-mini-tts")
OPENAI_TTS_VOICE = os.getenv("OPENAI_TTS_VOICE", "coral")
OPENAI_TTS_INSTRUCTIONS = os.getenv(
    "OPENAI_TTS_INSTRUCTIONS",
    "Parle en français avec une voix naturelle, captivante et dynamique, adaptée à une storytime.",
)

# --- Scheduling ---
PUBLISH_SLOTS = os.getenv("PUBLISH_SLOTS", "12:00,17:00,20:00").split(",")
MAX_CLIPS_PER_DAY = int(os.getenv("MAX_CLIPS_PER_DAY", 3))
CLIP_MIN_DURATION_SEC = int(os.getenv("CLIP_MIN_DURATION_SEC", 60))
CLIP_MAX_DURATION_SEC = int(os.getenv("CLIP_MAX_DURATION_SEC", 150))
TIMEZONE = os.getenv("TIMEZONE", "Africa/Ouagadougou")

# --- Shorts envoyés directement au bot ---
# L'API Bot Telegram publique limite actuellement les téléchargements à 20 Mo.
TELEGRAM_UPLOAD_MAX_MB = max(1, min(int(os.getenv("TELEGRAM_UPLOAD_MAX_MB", 19)), 20))
UPLOADED_SHORT_MAX_DURATION_SEC = max(1, min(
    int(os.getenv("UPLOADED_SHORT_MAX_DURATION_SEC", 180)), 180
))
MANUAL_SCHEDULE_MAX_DAYS = int(os.getenv("MANUAL_SCHEDULE_MAX_DAYS", 365))
MANUAL_SCHEDULE_MIN_LEAD_MINUTES = int(
    os.getenv("MANUAL_SCHEDULE_MIN_LEAD_MINUTES", 15)
)

# --- File de traitements persistante ---
JOB_WORKER_CONCURRENCY = max(1, int(os.getenv("JOB_WORKER_CONCURRENCY", 1)))
JOB_POLL_INTERVAL_SEC = max(0.5, float(os.getenv("JOB_POLL_INTERVAL_SEC", 2)))
JOB_MAX_ATTEMPTS = max(1, int(os.getenv("JOB_MAX_ATTEMPTS", 2)))

# --- Facturation (mode manuel pour le MVP) ---
MANUAL_PAYMENT_INSTRUCTIONS = os.getenv(
    "MANUAL_PAYMENT_INSTRUCTIONS",
    "Effectue le paiement par Orange Money ou Moov Money, puis transmets la référence au support.",
)

# --- DB ---
DATABASE_PATH = BASE_DIR / os.getenv("DATABASE_PATH", "db/shortpilot.sqlite3")

# --- Storage locale ---
TMP_DIR = BASE_DIR / "storage" / "tmp"
PROCESSED_DIR = BASE_DIR / "storage" / "processed"
LOGS_DIR = BASE_DIR / "logs"
