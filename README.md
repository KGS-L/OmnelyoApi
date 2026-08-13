# ShortPilot Platform API

[![CI](https://github.com/KGS-L/shortpilot-platform-api/actions/workflows/ci.yml/badge.svg)](https://github.com/KGS-L/shortpilot-platform-api/actions/workflows/ci.yml)

Backend de **ShortPilot**, une plateforme de création, de
programmation et de publication de vidéos courtes. Le dépôt réunit actuellement :

- un bot Telegram lié au compte web et à son workspace ;
- un pipeline de création de vidéos exécuté par des workers PostgreSQL ;
- une API FastAPI multi-tenant destinée au frontend SaaS ;
- une authentification par email/OTP et Google ;
- la publication vers YouTube, TikTok, Facebook et Instagram ;
- une base multi-tenant PostgreSQL et une abstraction de facturation extensible.

> Le frontend SaaS n'est pas inclus dans ce dépôt. Le backend métier et ses
> connecteurs sont en place. La tarification, les quotas, l'envoi d'emails et le
> prestataire de paiement doivent encore être décidés ou raccordés.

## Fonctionnalités

### Automatisation vidéo et Telegram

- soumission d'une vidéo source par URL ;
- téléchargement avec `yt-dlp` ;
- détection de scènes et découpage avec PySceneDetect et FFmpeg ;
- génération d'un storytime avec OpenAI, Gemini, Groq, xAI/Grok, Mistral ou Kimi ;
- synthèse vocale avec OpenAI TTS ;
- suppression de l'audio original et ajout d'une carte visuelle ;
- archivage des rendus sur Cloudflare R2 (API compatible S3) ;
- publication via YouTube, TikTok, Facebook Pages/Reels et Instagram Reels ;
- import d'un Short Telegram dans le workspace, puis choix des destinations sur le web ;
- file durable PostgreSQL avec leases, heartbeat, retry et reprise après redémarrage ;
- polling et réconciliation des statuts de publication chez les fournisseurs.

### Socle SaaS

- API REST FastAPI avec documentation OpenAPI ;
- comptes utilisateurs PostgreSQL ;
- connexion passwordless par code OTP stocké temporairement dans Redis ;
- connexion Google Identity Services ;
- access tokens JWT et refresh tokens rotatifs/révocables ;
- workspaces et rôles `owner`, `admin` et `member` ;
- CRUD des chaînes, vidéos, jobs et publications, avec publication par lots ;
- upload vidéo en streaming avec limite de taille et validation MIME binaire ;
- URLs R2 signées et clés isolées par workspace/job ;
- liaison web ↔ Telegram par jeton Redis haché, expirant et à usage unique ;
- credentials OAuth sociaux chiffrés en base ;
- logs JSON corrélés, rate limiting Redis et journal d'audit PostgreSQL ;
- migrations PostgreSQL avec Alembic ;
- `BillingService` indépendant du prestataire de paiement ;
- prototype historique de paiement manuel Mobile Money, non activé dans l'API ;
- environnements Docker distincts pour le développement et la production ;
- CI GitHub Actions et déploiement VPS manuel.

## Architecture actuelle

```text
Utilisateur Telegram ─┐                 ┌─ Frontend web
                      ▼                 ▼
                    API FastAPI multi-tenant
                      │              │
                      ▼              ▼
                 PostgreSQL         Redis
           comptes, workspaces,     OTP, états OAuth,
           vidéos, jobs, audit      signaux des workers
                      │
                      ▼
               Workers indépendants
       INGEST → PROCESS → RENDER → PUBLISH
                      │
              ┌───────┴────────┐
              ▼                ▼
        Cloudflare R2    YouTube / TikTok /
                        Facebook / Instagram

             Caddy termine HTTPS en production
```

**PostgreSQL est la source de vérité** des nouveaux flux : identités, workspaces,
connexions sociales, vidéos, jobs, publications et audit. Redis conserve seulement
les données temporaires et les signaux de réveil ; les workers continuent à poller
PostgreSQL si Redis est indisponible. L'ancien code SQLite reste isolé dans `db/`
et `scheduler/` uniquement pour migrer ou vérifier les données historiques.

## Structure du dépôt

```text
shortpilot-platform-api/
├── api/                         # API, auth, routes métier et intégrations sociales
├── billing/                     # BillingService et adaptateurs de paiement
├── bot/                         # bot Telegram et callback OAuth YouTube
├── core/                        # pipeline vidéo, LLM, TTS, R2 et YouTube
├── db/                          # base SQLite historique du bot
├── migrations/                  # migrations Alembic PostgreSQL
├── scheduler/                   # pipeline SQLite historique, isolé
├── workers/                     # handlers INGEST/PROCESS/RENDER/PUBLISH
├── tests/                       # tests unitaires et intégration PostgreSQL
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
- une application TikTok développeur pour le connecteur TikTok ;
- une application Meta avec les permissions Facebook/Instagram nécessaires ;
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

## Configuration des plateformes sociales

Deux identifiants Google différents sont utilisés :

1. **OAuth YouTube** autorise ShortPilot à publier sur une chaîne. Crée un client
   OAuth de type « Application Web », configure exactement l'URI présente dans
   `YOUTUBE_REDIRECT_URI`, puis ajoute le JSON dans `credentials/`.
2. **Google Identity Services** connecte les utilisateurs du futur frontend SaaS.
   Son client Web doit être renseigné dans `GOOGLE_WEB_CLIENT_ID`.

Les connexions SaaS démarrent avec
`POST /v1/workspaces/{workspace_id}/integrations/social/{platform}/connect`.
Le callback générique est basé sur `SOCIAL_OAUTH_CALLBACK_BASE_URL`. TikTok reste
en mode sandbox tant que l'application n'a pas passé son audit. Facebook requiert
une Page et Instagram un compte professionnel lié à une Page ; les permissions
Meta avancées doivent être validées avant la production.

La commande Telegram `/connect_youtube` appartient encore au mode historique. Le
flux SaaS recommandé consiste à connecter les plateformes depuis l'interface web.

## Variables d'environnement principales

La liste exhaustive et les valeurs d'exemple se trouvent dans
[`.env.example`](.env.example).

| Groupe | Variables principales |
|---|---|
| Telegram | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_BOT_USERNAME`, `TELEGRAM_LINK_TTL_SECONDS` |
| OAuth social | `SOCIAL_CREDENTIALS_KEY`, `SOCIAL_OAUTH_CALLBACK_BASE_URL`, `SOCIAL_OAUTH_STATE_TTL_SECONDS` |
| YouTube | `YOUTUBE_CLIENT_SECRETS_FILE` |
| TikTok | `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`, `TIKTOK_SANDBOX_MODE` |
| Meta | `META_APP_ID`, `META_APP_SECRET`, `META_GRAPH_API_VERSION` |
| Stockage R2 | `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET_NAME`, `R2_ENDPOINT_URL` |
| Storytime | `LLM_PROVIDER` et les couples `<PROVIDER>_API_KEY` / `<PROVIDER>_MODEL` |
| Voix | `OPENAI_API_KEY`, `OPENAI_TTS_MODEL`, `OPENAI_TTS_VOICE` |
| Programmation | `PUBLISH_SLOTS`, `MAX_CLIPS_PER_DAY`, `TIMEZONE` |
| Limites vidéo | `TELEGRAM_UPLOAD_MAX_MB`, `UPLOADED_SHORT_MAX_DURATION_SEC`, `VIDEO_UPLOAD_MAX_BYTES` |
| Backend SaaS | `API_DATABASE_URL`, `REDIS_URL`, `API_JWT_SECRET`, `FRONTEND_ORIGINS` |
| Protection API | `API_RATE_LIMIT_ENABLED`, `API_RATE_LIMIT_PER_MINUTE` |
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
| `/cancel UUID` | annuler un job PostgreSQL encore en attente |
| URL de vidéo | créer une vidéo et un job `INGEST` dans le workspace lié |
| Fichier vidéo | importer un Short prêt à publier dans le workspace lié |

Pour un fichier envoyé directement, la légende accepte :

```text
auto | Mon titre de Short
```

ou une date exprimée dans le fuseau `TIMEZONE` :

```text
2026-08-20 17:00 | Mon titre de Short
```

L'utilisateur doit d'abord connecter Telegram depuis **Paramètres → Intégrations
→ Telegram** sur le web. Le lien `t.me` généré expire après dix minutes et ne peut
être consommé qu'une fois.

La Bot API Telegram limite actuellement le téléchargement configuré à 20 Mo au
maximum ; le projet utilise 19 Mo par défaut. La durée maximale configurable est
de 180 secondes. Une vidéo importée est ensuite publiée vers les plateformes
choisies depuis l'interface web.

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
| `GET/PATCH` | `/v1/workspaces/{workspace_id}` | consulter ou modifier un workspace |
| `GET/POST/PATCH/DELETE` | `/v1/workspaces/{workspace_id}/channels` | gérer les chaînes sociales |
| `POST` | `/v1/workspaces/{workspace_id}/videos/upload` | envoyer une vidéo en streaming |
| `GET/POST/PATCH/DELETE` | `/v1/workspaces/{workspace_id}/videos` | gérer les vidéos et leurs URLs signées |
| `GET/POST` | `/v1/workspaces/{workspace_id}/jobs` | créer et suivre les traitements |
| `POST` | `/v1/workspaces/{workspace_id}/jobs/{job_id}/cancel` | annuler un job en attente |
| `GET/POST/PATCH` | `/v1/workspaces/{workspace_id}/publications` | gérer les publications |
| `POST` | `/v1/workspaces/{workspace_id}/publications/batch` | créer plusieurs destinations |
| `POST` | `/v1/workspaces/{workspace_id}/publications/batch/publish` | publier un lot de destinations |
| `POST` | `/v1/workspaces/{workspace_id}/integrations/social/{platform}/connect` | démarrer OAuth social |
| `POST` | `/v1/workspaces/{workspace_id}/integrations/telegram/link` | générer le lien Telegram à usage unique |
| `GET/DELETE` | `/v1/workspaces/{workspace_id}/integrations/telegram` | vérifier ou révoquer Telegram |
| `GET` | `/v1/workspaces/{workspace_id}/audit-events` | consulter l'audit, rôle admin requis |

Les réponses incluent `X-Request-ID`. Le rate limiting s'appuie sur Redis et
fonctionne en mode fail-open si Redis est momentanément indisponible. Les jobs
exposent une progression de 0 à 100 et peuvent être suivis par polling.

L'émetteur d'emails est encore une interface : avant la production, il faut le
relier à un service transactionnel (par exemple Brevo, Resend ou SMTP). En
développement uniquement, `EXPOSE_DEV_OTP=true` renvoie le code dans la réponse.

Plus de détails dans [BACKEND_SAAS.md](BACKEND_SAAS.md).

## Facturation

La couche PostgreSQL de paiement expose un checkout commun pour Dodo Payments et
MoneyFusion. Dodo gère les abonnements et vérifie cryptographiquement ses
webhooks. MoneyFusion est limité aux achats ponctuels XOF : chaque notification
est confirmée côté serveur avec `get_payment(token)` avant tout changement local.
Les prix viennent exclusivement de `provider_price_mappings` et jamais du client.

Routes disponibles lorsque `BILLING_ENABLED=true` :

- `POST /v1/workspaces/{workspace_id}/billing/checkout` ;
- `POST /v1/workspaces/{workspace_id}/billing/portal` pour Dodo ;
- `POST /v1/billing/webhooks/dodo` ;
- `POST /v1/billing/webhooks/moneyfusion` ;
- `GET|POST /v1/billing/callbacks/moneyfusion`.

Cette couche enregistre et valide les paiements, mais n'accorde pas encore de
crédits et n'applique pas encore les quotas du produit final.

L'atelier décrit dans [IMPLEMENTATION_BACKEND.md](IMPLEMENTATION_BACKEND.md) doit
d'abord fixer la cible, l'unité de crédit, les quotas, les remboursements et les
moyens de paiement. Consulte ensuite [BILLING.md](BILLING.md) pour raccorder le
prestataire retenu.

## Tests et migrations

Exécuter la suite de CI localement :

```bash
pip install -r requirements-ci.txt
python -m pytest -q
python -m compileall -q api billing bot core db scheduler workers tests migrations
```

Appliquer les migrations PostgreSQL :

```bash
alembic upgrade head
```

Le workflow CI exécute les tests, vérifie la syntaxe Python, applique Alembic sur
un PostgreSQL éphémère et valide les fichiers Compose.

La suite PostgreSQL peut aussi être exécutée contre une base déjà migrée :

```bash
API_DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/database \
python -B -m unittest tests.integration_workspace_postgres -v
```

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
- configure `SOCIAL_CREDENTIALS_KEY` avec une clé Fernet stable et secrète ;
- limite les rôles autorisés à consulter le journal d'audit ;
- conserve les buckets R2 privés et utilise uniquement les URLs signées ;
- valide cryptographiquement les webhooks Dodo et confirme les notifications MoneyFusion via son API ;
- ne crédite jamais un paiement depuis une simple capture d'écran ;
- sauvegarde PostgreSQL et les objets R2 avant chaque migration importante.

## État du projet et prochaines étapes

- [x] pipeline vidéo PostgreSQL avec workers indépendants ;
- [x] archivage Cloudflare R2 ;
- [x] API FastAPI et modèle multi-tenant PostgreSQL ;
- [x] authentification OTP/Google et sessions rotatives ;
- [x] liaison sécurisée du compte Telegram au workspace ;
- [x] publication YouTube, TikTok, Facebook et Instagram ;
- [x] upload streaming, progression, rate limiting et audit ;
- [x] abstraction technique de facturation ;
- [x] Docker Compose, CI et déploiement VPS ;
- [ ] fournisseur d'emails transactionnels ;
- [ ] atelier business model, quotas et règles de crédits ;
- [x] endpoints de paiement Dodo/MoneyFusion et webhooks idempotents ;
- [ ] migration et validation des données SQLite historiques ;
- [ ] métriques, alertes, rétention et sauvegardes testées ;
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
conditions d'utilisation de chaque plateforme source et destination.
