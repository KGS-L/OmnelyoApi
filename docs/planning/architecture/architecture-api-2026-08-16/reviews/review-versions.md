# Revue d'architecture — Vérification versions & réalité

- **Cible :** `ARCHITECTURE-SPINE.md` (architecture-api-2026-08-16)
- **Lentille :** VERSION & REALITY VERIFICATION — chaque décision engagée a-t-elle été vérifiée contre le dépôt et le web, plutôt qu'assertée de mémoire ?
- **Revue :** 2026-08-16
- **Verdict : ** **pass-with-findings** (aucun bloquant ; 1 finding medium, 4 low)

## Méthode

1. Croisement systématique des 12 lignes du tableau Stack du spine contre `requirements.txt`, `requirements-ci.txt`, `Dockerfile`, `docker-compose.yml`, `docker-compose.prod.yml`, `docker-compose.override.yml`, `.github/workflows/ci.yml`.
2. Lecture effective des fichiers cités par le spine : `api/dependencies.py`, `workers/job_state.py`, `api/credit_service.py`, `api/integrations/social.py`, `core/storage_keys.py`, `migrations/env.py`, plus `api/routes/jobs.py`, `api/models.py`, `api/security/social_credentials.py`, `config.py` racine.
3. Recherche web (août 2026) sur la monnaie des versions : PostgreSQL 16/17/18, Redis OSS 7.x/8.x, python-telegram-bot, FastAPI, SQLAlchemy, redis-py, et le paquet `httpx2` (suspecté à tort d'être une faute de frappe).

## Findings

### F1 — MEDIUM — Écart d'interpréteur Python : spine/Docker 3.11, CI et dev local en 3.12

- **Localisation :** `Dockerfile:1` vs `.github/workflows/ci.yml:43` ; spine § Stack (« Python 3.11 (image python:3.11-slim-bookworm) »).
- **Preuve :** l'image de production est `python:3.11-slim-bookworm` (Dockerfile:1) et le `README.md:122` exige « Python 3.11+ », mais la CI exécute tests, migrations et suite d'intégration avec `python-version: "3.12"` (ci.yml:43). Les `__pycache__` résiduels des dossiers legacy (`db/`, `scheduler/`, `billing/`) sont tous `cpython-312.pyc` — le poste de dev tourne aussi en 3.12.
- **Impact :** le substrat déclaré (3.11) n'est pas celui sur lequel le code est vérifié en CI ni développé localement. Différences de comportement 3.11 vs 3.12 (warnings, stdlib,_deps) seraient détectées en production, pas en CI. À noter : Python 3.11 reste en support de sécurité jusqu'en octobre 2027 — pas un problème d'EOL, un problème de cohérence testé/déployé.
- **Recommandation :** aligner la CI sur 3.11 (le vrai substrat), ou modifier la ligne Stack du spine pour documenter l'écart volontaire (« image 3.11, CI 3.12 ») et son intention.

### F2 — LOW — Redis 7.4 en maintenance de sécurité seule ; la ligne active est Redis 8.x

- **Localisation :** spine § Stack (« Redis 7 (redis:7-alpine, appendonly) ») ; `docker-compose.yml:55`.
- **Preuve (web, août 2026) :** l'image `redis:7-alpine` suit la branche 7.4.x. D'après [endoflife.date/redis](https://endoflife.date/redis), Redis 7.4 n'est plus en support actif depuis le 2 mai 2025 et reçoit uniquement des correctifs de sécurité jusqu'au 1er décembre 2029 (7.4.10 = dernier patch). La ligne active est 8.x (8.10 courant, publiée le 29 juillet 2026), sous tri-licence RSALv2/SSPLv1/AGPLv3 — 7.4 n'offre pas l'option AGPL.
- **Impact :** pas EOL, pas « known-bad » → acceptable pour une ratification brownfield (la réalité du repo prime). Mais le spine engage un déploiement neuf sur une branche en maintenance de sécurité seulement, sans le consigner.
- **Recommandation :** conserver 7.4 (à jour en sécurité) et ajouter au Deferred une fenêtre de migration Redis 8.x, avec mention de la licence.

### F3 — LOW — Commentaire obsolète « SQLite » dans requirements.txt, contradictoire avec AD-1

- **Localisation :** `requirements.txt:31` — `SQLAlchemy>=2.0.32  # ORM léger sur SQLite`.
- **Preuve :** la stack SQLite a été retirée le 16 août 2026 (commit `823cf6b refactor: remove legacy SQLite stack (db/, scheduler/, billing/)` ; AGENTS.md ; AD-1). Les dossiers `db/`, `scheduler/`, `billing/` ne contiennent plus que des `__pycache__` — cohérent avec le Deferred « nettoyages inertes ».
- **Impact :** contradiction cosmétique dans le très fichier que le tableau Stack du spine référence ; risque de confusion pour un nouveau contributeur (« SQLite est-il encore là ? »).
- **Recommandation :** corriger le commentaire (une ligne, opportuniste via bmad-build).

### F4 — LOW — Le récit « bornes minimales, pas de pin » du spine omet les deux vrais pins et yt-dlp

- **Localisation :** spine § Stack (FastAPI « bornes minimales, pas de pin — voir Deferred ») et § Deferred (« Pin des dépendances ») ; `requirements.txt:5,52-53`.
- **Preuve :** `dodopayments>=1.111.0,<1.112` et `apiMoneyFusion>=0.1.4,<0.2` sont les **seules** dépendances épingées avec borne haute (répétables dans `requirements-ci.txt:18-19`) — une exception réelle à la politique « pas de pin » que le spine ne mentionne pas. Par ailleurs `yt-dlp>=2024.8.6`, seule dépendance dont la fraîcheur est fonctionnellement critique (blocages YouTube fréquents, utilisée par `core/downloader.py`), est absente du tableau Stack alors que FFmpeg y figure.
- **Impact :** le tableau Stack est une image partielle et légèrement inexacte des engagements de version réels.
- **Recommandation :** ajouter au Stack (ou en note) : paiements (SDK épinglés) et yt-dlp (dépendance à fraîcheur critique, non épinglée).

### F5 — LOW — « Overlay prod durci : read_only + tmpfs » est une généralisation : le bot n'est ni read_only ni tmpfs

- **Localisation :** spine § Structural Seed (enveloppe opérationnelle) ; `docker-compose.prod.yml:33-37`.
- **Preuve :** seuls `api` (prod.yml:18-21) et `worker` (prod.yml:28-31) reçoivent `read_only` + tmpfs ; `shortpilot-bot` n'a aucun durcissement filesystem en prod (il monte `./credentials:ro`, `bot_storage`, `bot_logs`). Probablement délibéré (le bot écrit des fichiers), mais le spine généralise sans distinguer.
- **Impact :** un lecteur du spine croirait les cinq services durcis uniformément.
- **Recommandation :** préciser « api + worker read_only/tmpfs ; bot en écriture contrainte par volumes ».

## Vérifications réussies (web + repo)

### Tableau Stack vs fichiers du dépôt — 12/12 lignes conformes

| Ligne Stack | Réalité repo | Statut |
| --- | --- | --- |
| Python 3.11 (`python:3.11-slim-bookworm`) | `Dockerfile:1` | Conforme (mais voir F1 : CI en 3.12) |
| FastAPI ≥ 0.115.0 | `requirements.txt:36` | Conforme. Courant upstream : 0.141.1 (29 juil. 2026, [PyPI](https://pypi.org/project/fastapi/)) — borne min saine et satisfaite |
| SQLAlchemy ≥ 2.0.32 (psycopg 3 ≥ 3.2.0) | `requirements.txt:31-32` | Conforme. Ligne 2.0 toujours active : 2.0.52 (11 août 2026, [sqlalchemy.org](https://www.sqlalchemy.org/download/)) |
| Alembic ≥ 1.13.2 | `requirements.txt:33` | Conforme (borne min ; ligne 1.x maintenue) |
| pydantic-settings ≥ 2.4.0 | `requirements.txt:39` | Conforme |
| PostgreSQL 16 (`postgres:16-alpine`) | `docker-compose.yml:33`, `ci.yml:21` | Conforme. PG16 supporté jusqu'au 9 nov. 2028, mineur 16.15 publié le 13 août 2026 ([postgresql.org](https://www.postgresql.org/support/versioning/)) ; PG17 (2024) et PG18 (25 sept. 2025) existent — non problématique, ratification brownfield |
| Redis 7 (`redis:7-alpine`, appendonly) | `docker-compose.yml:55-62` | Conforme au repo ; voir F2 pour la monnaie |
| python-telegram-bot ≥ 21.0 | `requirements.txt:2` | Conforme. Courant : v22.8 (12 juin 2026, [PyPI](https://pypi.org/project/python-telegram-bot/)) — la lignée 21+ est maintenue, borne min valide |
| boto3 ≥ 1.34.0 | `requirements.txt:20` | Conforme |
| uvicorn ≥ 0.30.0 | `requirements.txt:38` (`uvicorn[standard]`) | Conforme |
| FFmpeg binaire image | `Dockerfile:9` (`apt-get install ffmpeg`) | Conforme |
| Nginx + Certbot (`deploy/nginx/`) | `deploy/nginx/omnelyo.conf.template`, `security-headers.conf` ; certbot installé sur le VPS via apt (`docs/ci-cd.md:130`) | Conforme |

`requirements-ci.txt:21` contient `httpx2>=0.3.0` — vérifié par web car suspecté d'être une faute de frappe de `httpx` : c'est un vrai paquet, le TestClient de Starlette est désormais construit sur httpx2 et `httpx` simple y est déprécié ([starlette.dev/testclient](https://starlette.dev/testclient/)). Aucun finding.

### Affirmations factuelles sur le code — vérifiées par lecture

- **AD-3 :** `api/dependencies.py:47-57` — `get_current_workspace_membership` lève bien **404** (jamais 403) pour workspace absent/étranger ; `require_workspace_roles` (l. 68) n'émet 403 que pour un membre sous-équipé. `core/storage_keys.py:31-32` — `belongs_to_workspace` revérifie le préfixe `workspaces/{ws}/` **et** bloque `..`.
- **AD-4 :** `workers/job_state.py:18-29` — `claim_next_job` : `with_for_update(skip_locked=True)`, statut QUEUED, `available_at <= now`, `attempts < max_attempts`. Propriété = RUNNING + `worker_id` (l. 172-181) ; `heartbeat_job` (l. 45) et `recover_stale_jobs` (l. 139) existent et sont les seules reprises. Le signal Redis (`workers.signals.notify_workers`, appelé dans `api/routes/jobs.py:152-159`) est non bloquant.
- **AD-5 :** `api/routes/jobs.py:75-79` — le retry **refuse** (409) un job FAILED ayant épuisé `max_attempts` ; l'annulation n'accepte que QUEUED (l. 59-63). `workers/job_state.py:129` — `defer_job` décrémente `attempts` : `JobDeferred` refile sans consommer de tentative.
- **AD-7 :** `api/credit_service.py:58-63` — solde = `SUM(amount)` sur ledger append-only ; cycle reserve/capture/release (l. 94-178) avec idempotence. Contraintes uniques réelles en base : `uq_credit_reservations_account_idem`, `uq_credit_ledger_account_idem`, `uq_payment_intents_ws_provider_idem` (`api/models.py:557,777,802`) ; table `provider_price_mappings` (`api/models.py:656`). Vocabulaire d'erreurs conforme (402 crédits en `routes/jobs.py:149`, 429 quota l. 140, 404 partout).
- **AD-8 :** `api/integrations/social.py:84-151` — ABC `SocialPublisher` (adaptateurs sans état) + `SocialPublisherRegistry`. Chiffrement Fernet confirmé dans `api/security/social_credentials.py:2-12` avec `SOCIAL_CREDENTIALS_KEY`.
- **AD-9 :** `config.py` racine (l. 14-17) fait bien `os.getenv` + `mkdir` à l'import — le crash latent en prod `read_only` décrit est réel ; cohérent avec le statut « migration en attente ».
- **Migrations :** `migrations/env.py:11` — URL depuis `get_settings().api_database_url` (donc `API_DATABASE_URL`). Conforme.
- **CI/déploiement :** `ci.yml` fait exactement ce que le spine annonce (tests unitaires + couverture, PostgreSQL 16 éphémère, `alembic upgrade head`, suite d'intégration, validation des deux fichiers Compose) ; `deploy.yml` se déclenche sur CI réussie en `main` (workflow_run) vers GHCR — conforme à « image immuable SHA → GHCR, déploiement staging sur main ».
- **Dettes listées au Deferred :** exactes — APScheduler/moviepy/ffmpeg-python/playwright toujours présents dans `requirements.txt:8,10,17,48` ; `db/`, `scheduler/`, `billing/` réduits à des `__pycache__` (vérifié par `find`).

## Sources web

- [PostgreSQL — Versioning policy](https://www.postgresql.org/support/versioning/) · [endoflife.date/postgresql](https://endoflife.date/postgresql) · [PostgreSQL 18 release](https://www.postgresql.org/about/news/postgresql-18-released-3142/)
- [endoflife.date/redis](https://endoflife.date/redis)
- [PyPI — python-telegram-bot](https://pypi.org/project/python-telegram-bot/)
- [PyPI — fastapi](https://pypi.org/project/fastapi/)
- [SQLAlchemy — Download](https://www.sqlalchemy.org/download/)
- [PyPI — redis (redis-py)](https://pypi.org/project/redis/) · [redis-py docs](https://redis.readthedocs.io/)
- [Starlette — TestClient (httpx2)](https://starlette.dev/testclient/)
