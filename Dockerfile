# Robot Short Yt — image Docker
FROM python:3.11-slim

# ffmpeg est requis par moviepy / ffmpeg-python pour le découpage vidéo
# libgl1 et libglib2.0-0 sont requis par opencv (utilisé par PySceneDetect)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Optionnel : Navigateur headless pour Playwright (non requis par notre version Pillow d'overlay.py)
# Supprimer ou commenter pour réduire la taille de l'image de ~70% (d'environ 2.5 Go à 800 Mo)
RUN python -m playwright install --with-deps chromium || true

COPY . .

# Port du serveur callback OAuth (bot/oauth_server.py), utilisé en interne
# par le reverse proxy Caddy (voir docker-compose.yml)
EXPOSE 8420

CMD ["python", "main.py"]
