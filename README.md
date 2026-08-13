# Robot Short Yt

Bot Telegram qui automatise la création et la publication de YouTube Shorts :
tu envoies un lien de vidéo, le bot la découpe en plusieurs séquences, génère une
narration "storytime" avec voix IA, et programme automatiquement la publication
sur YouTube (plusieurs shorts par jour, à horaires fixes).

## ✨ Fonctionnalités

- 🔗 Soumission d'une vidéo source via un simple lien envoyé au bot Telegram
- 📱 Envoi direct de Shorts personnels avec date et titre facultatifs
- ✂️ Découpage intelligent en clips de 1 à 2m30 (détection de scènes, pas de coupe fixe arbitraire)
- 🔇 Suppression automatique de l'audio original
- 🤖 Génération d'un texte narratif ("storytime") via LLM, calibré sur la durée du clip
- 🗣️ Génération de la voix off par synthèse vocale IA
- 🖼️ Incrustation d'une card visuelle personnalisée (style commentaire) en haut de la vidéo
- ☁️ Archivage des clips finaux sur stockage objet (Cloudflare R2)
- 📅 Programmation automatique sur YouTube (2-3 publications/jour, créneaux configurables)
- 🔐 Connexion YouTube en un clic depuis Telegram (OAuth2 via lien, aucune manipulation manuelle)
- 🛎️ Notifications Telegram (résultat du découpage, confirmation de programmation, alertes en cas d'échec)
- ♻️ File persistante : les travaux en attente survivent aux redémarrages
- 🐳 Entièrement dockerisé, déployable sur n'importe quel VPS

## 🏗️ Architecture

```
Toi ──(lien vidéo)──▶ Bot Telegram
                            │
                            ▼
                    ┌───────────────┐
                    │  Scheduler /  │
                    │  Orchestrateur│
                    └───────┬───────┘
                            │
        ┌───────────────────┼───────────────────┐
        ▼                   ▼                    ▼
  Téléchargement      Découpage vidéo      Génération contenu
  (yt-dlp)            (PySceneDetect       (LLM storytime
                        + ffmpeg)            + TTS voix off
                                              + card overlay)
        │                   │                    │
        └───────────────────┼────────────────────┘
                            ▼
                    Upload archive (R2)
                            │
                            ▼
                    Upload programmé YouTube
                    (API Data v3, publishAt)
                            │
                            ▼
                    Notification Telegram
                            │
                            ▼
              Watchdog quotidien (vérifie que
              les publications prévues ont bien
              eu lieu, alerte sinon)
```

Toute l'authentification YouTube passe par OAuth2 **piloté depuis Telegram** :
la commande `/connect_youtube` génère un lien d'autorisation Google que tu ouvres
dans ton navigateur (peu importe l'appareil). Un petit serveur web embarqué reçoit
la confirmation de Google et termine la connexion automatiquement — aucune
manipulation sur le serveur lui-même.

## 📁 Structure du projet

```
RobotShortYt/
├── main.py                    # point d'entrée (bot + serveur OAuth)
├── config.py                   # chargement de la configuration (.env)
├── Dockerfile
├── docker-compose.yml
├── Caddyfile                    # reverse proxy HTTPS automatique
│
├── bot/
│   ├── telegram_bot.py           # initialisation du bot
│   ├── handlers.py                # commandes (/status, /connect_youtube...)
│   └── oauth_server.py             # serveur web du callback OAuth
│
├── core/
│   ├── downloader.py               # téléchargement vidéo (yt-dlp)
│   ├── scene_detect.py              # détection de scènes
│   ├── video_cutter.py               # découpage final (ffmpeg)
│   ├── storytime.py                   # génération du texte narratif (LLM)
│   ├── tts.py                          # génération de la voix off
│   ├── overlay.py                       # génération + incrustation de la card
│   ├── storage_r2.py                     # archivage Cloudflare R2
│   ├── youtube_auth.py                    # OAuth2 YouTube (flow web)
│   └── youtube_uploader.py                 # upload + programmation YouTube
│
├── db/
│   ├── schema.sql                  # définition des tables
│   ├── models.py                    # structures de données
│   └── database.py                   # connexion SQLite
│
├── scheduler/
│   ├── scheduler.py                # orchestration du pipeline + créneaux
│   └── watchdog.py                  # vérification quotidienne des publications
│
├── credentials/                 # secrets YouTube (ignoré par git)
├── storage/                     # fichiers vidéo temporaires et finaux
├── logs/
└── db/                          # base SQLite (créée au premier lancement)
```

## 🧰 Prérequis

- Un VPS (Linux) avec **Docker** et **Docker Compose** installés
- Un **nom de domaine** pointant vers l'IP du VPS (nécessaire pour le HTTPS, requis par Google OAuth)
- Un compte **Google Cloud** (gratuit) pour créer les identifiants API YouTube
- Un bot **Telegram** (créé via [@BotFather](https://t.me/BotFather))
- Un compte **Cloudflare R2** (ou autre stockage compatible S3) pour l'archivage
- Une clé API **LLM** (OpenAI, Gemini, Groq, xAI, Mistral ou Kimi)
- Une clé **OpenAI API** pour la voix off TTS

## 🚀 Installation

### 1. Cloner le projet

```bash
git clone https://github.com/ton-compte/RobotShortYt.git
cd RobotShortYt
```

### 2. Créer le bot Telegram

1. Ouvre une conversation avec [@BotFather](https://t.me/BotFather)
2. `/newbot`, choisis un nom et un username
3. Récupère le token fourni (format `123456:ABC-DEF...`)

### 3. Configurer l'API YouTube (Google Cloud Console)

1. Crée un projet sur [console.cloud.google.com](https://console.cloud.google.com/)
2. Active l'API **YouTube Data API v3** (menu *APIs et services > Bibliothèque*)
3. Configure l'**écran de consentement OAuth** (type *External*, ajoute ton compte comme *Test user*)
4. Crée un **ID client OAuth** de type **Application Web**
5. Dans *URIs de redirection autorisés*, ajoute : `https://ton-domaine.com/oauth2callback`
6. Télécharge le fichier JSON généré, place-le dans `credentials/client_secret.json`

### 4. Configurer les variables d'environnement

```bash
cp .env.example .env
```

Édite `.env` et renseigne toutes les valeurs (voir tableau ci-dessous).

### 5. Configurer le domaine dans le Caddyfile

Édite `Caddyfile` et remplace `ton-domaine.com` par ton vrai domaine.

### 6. Lancer

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

Vérifie les logs :

```bash
docker compose logs -f robot-short-yt
```

### 7. Connecter ta chaîne YouTube

Dans Telegram, envoie `/connect_youtube` à ton bot. Clique le lien reçu,
autorise l'accès avec ton compte Google — la connexion se termine automatiquement.

## ⚙️ Configuration (`.env`)

| Variable | Description |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Token du bot (via @BotFather) |
| `TELEGRAM_ADMIN_CHAT_ID` | Ton chat ID Telegram (pour les notifications/alertes) |
| `YOUTUBE_CLIENT_SECRETS_FILE` | Chemin vers le JSON téléchargé de Google Cloud |
| `YOUTUBE_TOKEN_FILE` | Chemin où le token OAuth sera sauvegardé |
| `YOUTUBE_REDIRECT_URI` | URL publique du callback, ex: `https://ton-domaine.com/oauth2callback` |
| `OAUTH_CALLBACK_PORT` | Port interne du serveur callback (défaut `8420`) |
| `R2_ACCOUNT_ID` / `R2_ACCESS_KEY_ID` / `R2_SECRET_ACCESS_KEY` | Identifiants Cloudflare R2 |
| `R2_BUCKET_NAME` | Nom du bucket R2 |
| `R2_ENDPOINT_URL` | Endpoint R2 (ex: `https://<account_id>.r2.cloudflarestorage.com`) |
| `LLM_PROVIDER` | Fournisseur du storytime : `openai`, `gemini`, `groq`, `xai`, `mistral` ou `kimi` |
| `<PROVIDER>_API_KEY` / `<PROVIDER>_MODEL` | Clé et modèle du fournisseur sélectionné |
| `OPENAI_API_KEY` | Clé OpenAI, également utilisée pour la voix off |
| `OPENAI_TTS_MODEL` / `OPENAI_TTS_VOICE` | Modèle et voix OpenAI TTS |
| `PUBLISH_SLOTS` | Créneaux horaires de publication, ex: `12:00,17:00,20:00` |
| `MAX_CLIPS_PER_DAY` | Nombre max de shorts publiés par jour |
| `CLIP_MIN_DURATION_SEC` / `CLIP_MAX_DURATION_SEC` | Durée min/max des clips générés |
| `TIMEZONE` | Fuseau horaire pour la programmation |
| `DATABASE_PATH` | Chemin de la base SQLite |
| `TELEGRAM_UPLOAD_MAX_MB` | Taille maximale d'un Short reçu par Telegram (maximum technique : 20 Mo) |
| `UPLOADED_SHORT_MAX_DURATION_SEC` | Durée maximale d'un Short importé (maximum YouTube : 180 s) |
| `MANUAL_SCHEDULE_MIN_LEAD_MINUTES` | Délai minimal avant une programmation manuelle |
| `JOB_WORKER_CONCURRENCY` | Nombre maximal de vidéos traitées simultanément (défaut recommandé : 1) |
| `JOB_MAX_ATTEMPTS` | Nombre maximal de prises en charge après interruption |

## 💬 Commandes du bot

| Commande | Description |
|---|---|
| `/connect_youtube` | Connecte (ou reconnecte) une chaîne YouTube |
| `/status` | Affiche l'état des vidéos en cours de traitement / programmées |
| `/queue` | Affiche les dix derniers traitements et leur état |
| `/cancel ID` | Annule un traitement qui n'a pas encore commencé |
| *(lien vidéo)* | Soumet une nouvelle vidéo source pour découpage et programmation |
| *(fichier vidéo)* | Programme un Short personnel, automatiquement ou à une date choisie |

### Envoyer son propre Short

Envoie la vidéo directement au bot, comme vidéo Telegram ou comme fichier vidéo.
Par défaut, elle sera placée au prochain créneau disponible. La vidéo doit être
verticale ou carrée, durer au maximum 3 minutes et respecter la taille configurée
(19 Mo par défaut à cause de la limite de téléchargement de la Bot API Telegram).

La légende permet de choisir le titre et la programmation :

```text
auto | Mon titre de Short
```

ou, pour imposer une date dans le fuseau `TIMEZONE` :

```text
2026-08-20 17:00 | Mon titre de Short
```

Pour programmer plusieurs Shorts, envoie chaque vidéo séparément avec sa propre
légende. Le bot refuse les collisions de créneaux et applique `MAX_CLIPS_PER_DAY`
par utilisateur.

### File de traitements

Chaque lien ou fichier reçoit un identifiant, par exemple `#12`. `/queue` affiche
les états `queued`, `running`, `completed`, `failed` ou `cancelled`. La commande
`/cancel 12` fonctionne tant que le job est encore `queued`. Un job déjà lancé ne
peut pas être interrompu brutalement, afin d'éviter un fichier ou un upload YouTube
partiellement créé.

Au démarrage, les jobs marqués `running` lors d'un arrêt précédent sont remis en
attente s'ils n'ont pas dépassé `JOB_MAX_ATTEMPTS`. La concurrence vaut 1 par
défaut pour éviter que plusieurs encodages ffmpeg saturent le serveur.

## 🐳 Docker

Le projet est entièrement conteneurisé :

- **`robot-short-yt`** — le bot, le pipeline de traitement et le serveur OAuth interne
- **`caddy`** — reverse proxy avec HTTPS automatique (Let's Encrypt) devant le callback OAuth

Aucun port du conteneur principal n'est exposé directement : seul Caddy est accessible
depuis l'extérieur (ports 80/443), ce qui limite la surface d'attaque.

```bash
docker compose up -d --build       # développement (charge automatiquement override)
docker compose logs -f             # suivre les logs de développement

# Production : n'ajoute jamais docker-compose.override.yml
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f
```

Les dossiers `credentials/`, `storage/`, `logs/` et `db/` sont montés en volumes :
les données persistent entre les redéploiements.

## 🌐 Backend SaaS

Le socle FastAPI/PostgreSQL/Redis est séparé du bot historique. Pour le lancer en
développement :

```bash
docker compose up -d postgres redis api
```

La documentation interactive est disponible sur `http://localhost:8000/docs`.
Consulte [BACKEND_SAAS.md](BACKEND_SAAS.md) pour les routes d'authentification,
les sessions et le modèle multi-tenant. Le bot utilise encore SQLite pendant la
transition ; les comptes et workspaces web utilisent PostgreSQL.

## 🔒 Sécurité & bonnes pratiques

- Ne commit jamais `.env` ni `credentials/client_secret.json` (déjà exclus via `.gitignore`/`.dockerignore`)
- Un seul compte Google (celui ajouté comme *Test user*) peut se connecter tant que
  l'écran de consentement OAuth n'est pas passé en mode *Production* (suffisant pour un usage personnel)
- Chaque déploiement (bot + projet Google Cloud + domaine) est indépendant :
  ce projet peut être déployé plusieurs fois par différentes personnes, chacune avec ses propres clés

## 📜 Licence

À définir selon ton usage (MIT recommandé si tu comptes le partager publiquement).

## ⚠️ Avertissement

Ce projet republie du contenu vidéo à partir de sources externes. Assure-toi de
respecter les droits d'auteur et les conditions d'utilisation des plateformes
sources avant toute publication.
