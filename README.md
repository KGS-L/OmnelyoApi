# Robot Short Yt

Bot Telegram + pipeline automatisé qui transforme une vidéo YouTube longue en plusieurs
YouTube Shorts (1min–2m30) avec voix off storytime générée par IA, puis les programme
automatiquement sur YouTube (2-3 publications/jour, créneaux fixes 12h/17h/20h).

## Flow global

```
1. Toi -> envoies un lien YouTube au bot Telegram
2. downloader.py     -> télécharge la vidéo source (yt-dlp)
3. scene_detect.py   -> détecte les scènes (PySceneDetect)
4. video_cutter.py   -> fusionne/découpe en clips 1min-2m30, coupe le son original
5. storytime.py      -> génère le script narratif (API LLM)
6. tts.py            -> génère la voix off (API TTS)
7. overlay.py         -> génère + incruste la card "commentaire" (8s)
8. storage_r2.py     -> upload des clips finaux sur Cloudflare R2 (archive)
9. scheduler.py       -> calcule le prochain créneau libre (DB) et upload
                          programmé sur YouTube (privacyStatus=private + publishAt)
10. telegram_bot.py   -> notifie le résultat ("Vidéo découpée en X shorts, programmés...")
11. watchdog.py        -> cron quotidien : vérifie que les publications prévues ont
                          bien eu lieu, alerte via le bot sinon
```

## Structure du projet

```
RobotShortYt/
├── main.py                  # point d'entrée, lance le bot
├── config.py                 # chargement des variables d'environnement
├── requirements.txt
├── .env.example
│
├── bot/
│   ├── telegram_bot.py        # init du bot, polling/webhook
│   └── handlers.py            # commandes (/status, /pause...) + réception des liens
│
├── core/
│   ├── downloader.py           # téléchargement vidéo (yt-dlp)
│   ├── scene_detect.py          # détection de scènes (PySceneDetect)
│   ├── video_cutter.py          # découpage final + suppression audio (ffmpeg/moviepy)
│   ├── storytime.py              # génération du texte narratif (LLM)
│   ├── tts.py                     # génération de la voix off (TTS)
│   ├── overlay.py                  # génération + incrustation de la card
│   ├── storage_r2.py                # upload/gestion Cloudflare R2
│   └── youtube_uploader.py          # upload + programmation API YouTube
│
├── db/
│   ├── schema.sql               # définition des tables
│   ├── models.py                 # dataclasses / ORM léger
│   └── database.py                # connexion + requêtes (SQLite)
│
├── scheduler/
│   ├── scheduler.py               # calcul des créneaux, orchestration pipeline
│   └── watchdog.py                 # vérification quotidienne des publications
│
├── storage/
│   ├── tmp/                        # fichiers en cours de traitement (nettoyés après)
│   └── processed/                   # clips finaux avant upload
│
└── logs/
```

## Statut

🚧 Squelette initial — modules à implémenter un par un.
