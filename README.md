# ShortPilot Platform API

[![CI](https://github.com/KGS-L/shortpilot-platform-api/actions/workflows/ci.yml/badge.svg)](https://github.com/KGS-L/shortpilot-platform-api/actions/workflows/ci.yml)

Backend open source de **ShortPilot**, une plateforme de création, de
programmation et de publication de vidéos courtes. Le dépôt réunit actuellement :

- un bot Telegram capable de transformer une vidéo source en YouTube Shorts ;
- l'envoi et la programmation de Shorts déjà montés ;
- une API FastAPI destinée au futur frontend SaaS ;
- une authentification par email/OTP et Google ;
- une base multi-tenant PostgreSQL et une abstraction de facturation extensible.

> Le frontend SaaS n'est pas encore inclus dans ce dépôt. Le bot et le socle API
> sont opérationnels, tandis que certaines intégrations SaaS sont encore à
> connecter (envoi d'emails, routes de facturation et prestataire de paiement).

## Fonctionnalités

### Automatisation vidéo et Telegram

- soumission d'une vidéo source par URL ;
- téléchargement avec `yt-dlp` ;
- détection de scènes et découpage avec PySceneDetect et FFmpeg ;
- génération d'un storytime avec OpenAI, Gemini, Groq, xAI/Grok, Mistral ou Kimi ;
- synthèse vocale avec OpenAI TTS ;
- suppression de l'audio original et ajout d'une carte visuelle ;
- archivage des rendus sur Cloudflare R2 (API compatible S3) ;
- programmation et publication via YouTube Data API v3 ;
- réception directe d'un Short Telegram et programmation manuelle ou automatique ;
- file SQLite persistante, reprise après redémarrage et notifications Telegram ;
- watchdog de contrôle des publications.

### Socle SaaS

- API REST FastAPI avec documentation OpenAPI ;
- comptes utilisateurs PostgreSQL ;
- connexion passwordless par code OTP stocké temporairement dans Redis ;
- connexion Google Identity Services ;
- access tokens JWT et refresh tokens rotatifs/révocables ;
- workspaces et rôles `owner`, `admin` et `member` ;
- migrations PostgreSQL avec Alembic ;
- `BillingService` indépendant du prestataire de paiement ;
- paiement manuel Mobile Money disponible dans le domaine de facturation ;
- environnements Docker distincts pour le développement et la production ;
- CI GitHub Actions et déploiement VPS manuel.

## Architecture actuelle

```text
Utilisateur Telegram                         Futur frontend web
        │                                            │
        ▼                                            ▼
  Bot Telegram ──► file persistante SQLite      API FastAPI
        │                                       │        │
        ▼                                       ▼        ▼
  Pipeline vidéo                            PostgreSQL  Redis
  yt-dlp → scènes → storytime/TTS           comptes,   OTP
        → overlay → FFmpeg                   workspaces sessions
        │
        ├──► Cloudflare R2 (archive)
        └──► YouTube Data API (publication planifiée)

                 Caddy termine HTTPS en production
```

Le projet utilise temporairement deux stockages relationnels :

- **PostgreSQL** est la source de vérité du backend SaaS (utilisateurs,
  identités, workspaces et sessions) ;
- **SQLite** conserve encore la file du bot et les données métier historiques.

La migration complète des traitements vidéo vers PostgreSQL/Redis fait partie de
la prochaine phase du SaaS.

## Structure du dépôt

```text
shortpilot-platform-api/
├── api/                         # API FastAPI, auth et modèle multi-tenant
├── billing/                     # BillingService et adaptateurs de paiement
├── bot/                         # bot Telegram et callback OAuth YouTube
├── core/                        # pipeline vidéo, LLM, TTS, R2 et YouTube
├── db/                          # base SQLite historique du bot
├── migrations/                  # migrations Alembic PostgreSQL
├── scheduler/                   # file, programmation et watchdog
├── tests/                       # tests unitaires et sécurité API
├── .github/workflows/           # CI et déploiement VPS
├── docker-compose.yml           # services communs
├── docker-compose.override.yml  # développement, chargé automatiquement
├── docker-compose.prod.yml      # Caddy et configuration de production
├── Caddyfile                    # HTTPS et reverse proxy
├── Dockerfile
├── main.py                      # point d'entrée du bot
└── config.py                    # configuration du pipeline historique
```

## Prérequis

Pour un lancement avec Docker :

- Docker Engine et Docker Compose v2 ;
- un bot Telegram créé avec [@BotFather](https://t.me/BotFather) ;
- un projet Google Cloud avec YouTube Data API v3 activée ;
- un domaine pointant vers le serveur pour les callbacks OAuth en HTTPS ;
- un bucket Cloudflare R2 et ses identifiants S3 ;
- au moins une clé de fournisseur LLM ;
- une clé OpenAI pour la voix off.

Pour une installation sans Docker, Python 3.11+, PostgreSQL 16, Redis 7 et FFmpeg
sont nécessaires.

## Installation locale avec Docker

```bash
git clone https://github.com/KGS-L/shortpilot-platform-api.git
cd shortpilot-platform-api
cp .env.example .env
```

Renseigne ensuite `.env`, puis place le fichier OAuth YouTube téléchargé depuis
Google Cloud dans `credentials/client_secret.json`.

Lance toute la stack de développement :

```bash
docker compose up -d --build
docker compose ps
docker compose logs -f
```

`docker-compose.override.yml` est automatiquement appliqué en développement. Les
services locaux sont alors accessibles ici :

| Service | Adresse |
|---|---|
| API | `http://localhost:8000` |
| Swagger | `http://localhost:8000/docs` |
| PostgreSQL | `localhost:5432` |
| Redis | `localhost:6379` |
| Callback OAuth du bot | `localhost:8420` |

Pour ne lancer que le backend web :

```bash
docker compose up -d postgres redis api
```

## Configuration Google

Deux identifiants Google différents sont utilisés :

1. **OAuth YouTube** autorise ShortPilot à publier sur une chaîne. Crée un client
   OAuth de type « Application Web », configure exactement l'URI présente dans
   `YOUTUBE_REDIRECT_URI`, puis ajoute le JSON dans `credentials/`.
2. **Google Identity Services** connecte les utilisateurs du futur frontend SaaS.
   Son client Web doit être renseigné dans `GOOGLE_WEB_CLIENT_ID`.

Après le démarrage du bot, envoie `/connect_youtube` dans Telegram et ouvre le lien
d'autorisation reçu.

## Variables d'environnement principales

La liste exhaustive et les valeurs d'exemple se trouvent dans
[`.env.example`](.env.example).

| Groupe | Variables principales |
|---|---|
| Telegram | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ADMIN_CHAT_ID` |
| YouTube | `YOUTUBE_CLIENT_SECRETS_FILE`, `YOUTUBE_TOKEN_FILE`, `YOUTUBE_REDIRECT_URI` |
| Stockage R2 | `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET_NAME`, `R2_ENDPOINT_URL` |
| Storytime | `LLM_PROVIDER` et les couples `<PROVIDER>_API_KEY` / `<PROVIDER>_MODEL` |
| Voix | `OPENAI_API_KEY`, `OPENAI_TTS_MODEL`, `OPENAI_TTS_VOICE` |
| Programmation | `PUBLISH_SLOTS`, `MAX_CLIPS_PER_DAY`, `TIMEZONE` |
| Limites vidéo | `TELEGRAM_UPLOAD_MAX_MB`, `UPLOADED_SHORT_MAX_DURATION_SEC` |
| Backend SaaS | `API_DATABASE_URL`, `REDIS_URL`, `API_JWT_SECRET`, `FRONTEND_ORIGINS` |
| Auth Google | `GOOGLE_WEB_CLIENT_ID` |
| Domaines | `BOT_DOMAIN`, `API_DOMAIN` |

En production, utilise un secret `API_JWT_SECRET` aléatoire d'au moins 32
caractères et laisse `EXPOSE_DEV_OTP=false`.

## Commandes Telegram

| Commande ou contenu | Action |
|---|---|
| `/connect_youtube` | connecter ou reconnecter une chaîne YouTube |
| `/status` | consulter les traitements et publications |
| `/queue` | afficher les dix derniers jobs |
| `/cancel ID` | annuler un job encore en attente |
| URL de vidéo | lancer le pipeline de découpage et de publication |
| Fichier vidéo | programmer un Short déjà monté |

Pour un fichier envoyé directement, la légende accepte :

```text
auto | Mon titre de Short
```

ou une date exprimée dans le fuseau `TIMEZONE` :

```text
2026-08-20 17:00 | Mon titre de Short
```

La Bot API Telegram limite actuellement le téléchargement configuré à 20 Mo au
maximum ; le projet utilise 19 Mo par défaut. La durée maximale configurable est
de 180 secondes. Chaque vidéo doit être envoyée séparément.

## API SaaS

Toutes les routes applicatives sont préfixées par `/v1`.

| Méthode | Route | Description |
|---|---|---|
| `GET` | `/health` | état de l'API |
| `POST` | `/v1/auth/email/request-otp` | demander un code de connexion |
| `POST` | `/v1/auth/email/verify` | vérifier le code et recevoir les tokens |
| `POST` | `/v1/auth/google` | se connecter avec un Google ID Token |
| `POST` | `/v1/auth/refresh` | renouveler et faire tourner les tokens |
| `POST` | `/v1/auth/logout` | révoquer le refresh token |
| `GET` | `/v1/users/me` | retourner l'utilisateur authentifié |

L'émetteur d'emails est encore une interface : avant la production, il faut le
relier à un service transactionnel (par exemple Brevo, Resend ou SMTP). En
développement uniquement, `EXPOSE_DEV_OTP=true` renvoie le code dans la réponse.

Plus de détails dans [BACKEND_SAAS.md](BACKEND_SAAS.md).

## Facturation

Le code métier passe exclusivement par `BillingService`, afin de ne pas lier le
SaaS à Stripe ou à un autre prestataire. Le mode MVP prévoit la validation manuelle
d'un paiement Orange Money/Moov Money avec référence de transaction et attribution
idempotente.

À ce stade, la facturation n'est pas exposée par des routes FastAPI et aucun
webhook de prestataire automatique n'est activé. Consulte [BILLING.md](BILLING.md)
pour ajouter un adaptateur PayDunya, Dodo Payments, Paddle ou un autre fournisseur.

## Tests et migrations

Exécuter la suite de CI localement :

```bash
pip install -r requirements-ci.txt
python -B -m unittest discover -s tests -v
python -m compileall -q api billing bot core db scheduler tests
```

Appliquer les migrations PostgreSQL :

```bash
alembic upgrade head
```

Le workflow CI exécute les tests, vérifie la syntaxe Python, applique Alembic sur
un PostgreSQL éphémère et valide les fichiers Compose.

## Déploiement en production

Configure `BOT_DOMAIN` et `API_DOMAIN` dans le `.env` du VPS, puis lance :

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f
```

N'ajoute pas `docker-compose.override.yml` à cette commande : il expose les bases
et monte le code local pour le développement. En production, Caddy expose
uniquement les ports 80/443 et fournit HTTPS aux domaines du bot et de l'API.

Le workflow **Deploy production** est déclenché manuellement depuis GitHub
Actions. Les secrets VPS nécessaires et le fonctionnement du déploiement sont
documentés dans [CI_CD.md](CI_CD.md).

## Sécurité

- ne commit jamais `.env`, les tokens ou `credentials/client_secret.json` ;
- utilise des clés distinctes entre développement et production ;
- garde PostgreSQL et Redis non exposés sur Internet ;
- vérifie toujours le membership du workspace côté serveur ;
- valide cryptographiquement les futurs webhooks de paiement ;
- ne crédite jamais un paiement depuis une simple capture d'écran ;
- sauvegarde PostgreSQL et les objets R2 avant chaque migration importante.

## État du projet et prochaines étapes

- [x] pipeline vidéo Telegram et programmation YouTube ;
- [x] archivage Cloudflare R2 ;
- [x] API FastAPI et modèle multi-tenant PostgreSQL ;
- [x] authentification OTP/Google et sessions rotatives ;
- [x] abstraction de facturation et paiement manuel ;
- [x] Docker Compose, CI et déploiement VPS ;
- [ ] fournisseur d'emails transactionnels ;
- [ ] endpoints de facturation et premier adaptateur automatique ;
- [ ] migration de la file vidéo vers PostgreSQL/Redis ;
- [ ] API métier pour projets, vidéos, chaînes et programmations ;
- [ ] frontend SaaS.

## Documentation complémentaire

- [Analyse initiale du code](ANALYSE_CODE.md)
- [Architecture SaaS cible](ARCHITECTURE_SAAS.md)
- [Backend SaaS](BACKEND_SAAS.md)
- [Facturation](BILLING.md)
- [CI/CD](CI_CD.md)

## Licence et responsabilité

Aucune licence n'est encore fournie dans le dépôt. Ajoute un fichier `LICENSE`
avant de présenter officiellement le projet comme réutilisable en open source.

Tu dois disposer des droits nécessaires sur les vidéos traitées et respecter les
conditions d'utilisation des plateformes sources et de YouTube.
