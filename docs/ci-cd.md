# CI/CD backend Omnelyo

Le workflow `.github/workflows/ci.yml` teste le backend sur chaque push et pull
request. Après une CI réussie sur `main`, `.github/workflows/deploy.yml` construit
une image unique pour l'API, les migrations, le worker et le bot, puis la publie
dans GitHub Container Registry. Le VPS déploie toujours le tag immuable
correspondant au SHA Git, jamais seulement `staging-latest`.

## Configuration GitHub

Créer un environnement GitHub nommé `staging`. Une approbation manuelle peut y
être activée si chaque déploiement doit être validé.

| Secret             | Valeur attendue                          |
| ------------------ | ---------------------------------------- |
| `VPS_BACKEND_PATH` | `/home/admin/projects/omnelyo/backend`   |
| `GHCR_USERNAME`    | compte GitHub autorisé à lire le package |
| `GHCR_TOKEN`       | token GitHub limité à `read:packages`    |

Le `GITHUB_TOKEN` du workflow publie l'image. Le token GHCR dédié sert seulement
au téléchargement privé depuis le VPS.

Le job `deploy` utilise un runner GitHub auto-hébergé sur le VPS avec les labels
standards `self-hosted`, `Linux` et `X64`. La connexion du runner vers GitHub est
sortante : aucun accès SSH entrant depuis les runners GitHub n'est nécessaire.

## Préparation unique du VPS

```bash
install -d -m 750 /home/admin/projects/omnelyo/backend
cd /home/admin/projects/omnelyo/backend
touch .env
chmod 600 .env
```

Le fichier `.env` reste uniquement sur le VPS. Au premier déploiement, le
workflow appelle `scripts/bootstrap-vps-env.sh`. Le script compare `.env` à
`.env.production.example`, ajoute seulement les variables absentes et génère des
valeurs uniques pour PostgreSQL, Redis et JWT si nécessaire. Toute valeur déjà
renseignée est conservée : Resend, Telegram et les autres intégrations ne sont
jamais écrasés.

Les clés externes laissées vides (Resend, Telegram, paiements, OAuth, R2 et IA)
doivent ensuite être renseignées sur le VPS. Le premier déploiement peut donc
s'arrêter après le bootstrap tant que les variables obligatoires ne sont pas
complétées. Base minimale :

```dotenv
API_ENVIRONMENT=production
APP_DOMAIN=omnelyo.kgslab.com
API_DOMAIN=api-omnelyo.kgslab.com
BOT_DOMAIN=bot-omnelyo.kgslab.com
API_HOST_PORT=8100
BOT_HOST_PORT=8420
WEB_APP_URL=https://omnelyo.kgslab.com
FRONTEND_ORIGINS=https://omnelyo.kgslab.com

POSTGRES_DB=omnelyo
POSTGRES_USER=omnelyo
POSTGRES_PASSWORD=REMPLACER
API_DATABASE_URL=postgresql+psycopg://omnelyo:REMPLACER@postgres:5432/omnelyo
REDIS_PASSWORD=REMPLACER
REDIS_URL=redis://:REMPLACER@redis:6379/0
API_JWT_SECRET=REMPLACER_PAR_AU_MOINS_32_CARACTERES

EMAIL_PROVIDER=resend
EMAIL_FROM=Omnelyo <login@VOTRE_DOMAINE_VERIFIE>
RESEND_API_KEY=REMPLACER
EXPOSE_DEV_OTP=false

BILLING_ENABLED=false
DODO_ENVIRONMENT=test
TIKTOK_SANDBOX_MODE=true
```

Ajouter ensuite Telegram, OAuth, R2 et IA. Encoder les caractères spéciaux des
mots de passe dans les URL PostgreSQL et Redis.

## Déploiement et rollback

Un push sur `main` lance : tests, build GHCR, migrations, recréation des services
et contrôle de `https://api-omnelyo.kgslab.com/health`.

Si ce contrôle échoue, le workflow remet automatiquement l'image applicative
précédente. Il ne rétrograde jamais automatiquement la base de données.

Rollback manuel :

```bash
cd /home/admin/projects/omnelyo/backend
export BACKEND_IMAGE='ghcr.io/PROPRIETAIRE/omnelyo-backend:SHA_PRECEDENT'
docker compose -f docker-compose.yml -f docker-compose.prod.yml pull api worker shortpilot-bot
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --no-build api worker shortpilot-bot
curl --fail https://api-omnelyo.kgslab.com/health
```

Toute migration destructive exige une sauvegarde PostgreSQL testée et une
stratégie de compatibilité avant le déploiement.

## Configuration initiale de Nginx

Nginx est configuré une seule fois, séparément du workflow applicatif afin de
ne pas modifier les autres sites du VPS. Le script est idempotent, sauvegarde
une configuration Omnelyo existante et exécute `nginx -t` avant le rechargement.

Après avoir copié `scripts/configure-nginx.sh` et `deploy/nginx/` sur le VPS :

```bash
cd /home/admin/projects/omnelyo/backend
sudo bash scripts/configure-nginx.sh --no-tls
```

Le script vérifie automatiquement que les domaines API et bot pointent vers
`72.61.98.7` et attend leur propagation jusqu'à cinq minutes. Il s'arrête avant
de modifier Nginx si cette vérification échoue. Pour configurer Nginx et TLS en
une seule commande :

```bash
sudo bash scripts/configure-nginx.sh --email admin@example.com
```

Si Certbot est absent sur un VPS Ubuntu/Debian, le script installe
automatiquement `certbot` et `python3-certbot-nginx` avec `apt-get`.

Le script configure uniquement les proxys locaux du backend : API `8100` et bot
`8420`. Le domaine frontend et son port `3000` restent sous la responsabilité
du dépôt frontend. Le workflow de déploiement ne réexécute pas ce script.
