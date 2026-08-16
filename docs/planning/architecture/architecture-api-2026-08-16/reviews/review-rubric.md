# Revue du spine d'architecture — marche-rubrique (rubric walker)

- **Cible :** `ARCHITECTURE-SPINE.md` (altitude initiative, statut draft, 2026-08-16)
- **Lentille :** check-list « good spine » en 6 points (divergences, enforceabilité, Deferred, fraîcheur techno, ratification brownfield, couverture des dimensions)
- **Méthode :** chaque règle et affirmation factuelle du spine a été confrontée au code du dépôt (fichiers et lignes cités en annexe). Vérification exhaustive des 10 AD, du tableau Stack contre `requirements.txt` / `docker-compose.yml` / `docker-compose.prod.yml` / `Dockerfile` / `.github/workflows/`, et des Deferred contre `docs/decisions.md` et `docs/implementation-backend.md`.
- **Date :** 2026-08-16

## Verdict : **pass-with-findings**

Aucun finding critique ni haut. Le spine est remarquablement fidèle au brownfield (aucune contradiction constatée sur les 10 AD), chaque règle est ancrée dans du code réel et vérifiable, et aucun élément du Deferred n'autorise une divergence entre deux unités. Deux tensions moyennes et trois points bas restent à corriger.

---

## Marche item par item

### 1. Les vrais points de divergence pour le niveau inférieur — couverts, un oubli

Couverture constatée (chaque point a son ancrage code vérifié) :

| Divergence potentielle | Fixée par | Ancrage vérifié |
| --- | --- | --- |
| Deuxièmes persistances métier | AD-1 | `db/`, `scheduler/`, `billing/` ne contiennent plus que `__pycache__` ; `decisions.md` §2 confirme le retrait |
| Statut réel de Redis | AD-2 | OTP (`api/routes/auth.py:27-49`), OAuth state (`api/integrations/social_oauth.py:48-52`), jeton Telegram (`api/routes/telegram_integration.py:52-53`) consomment Redis sans dégradation ; rate-limit fail-open (`api/observability.py:90`) ; wakeup dégradé en polling (`workers/signals.py`, `workers/runner.py:52-56,147`) |
| Fuite cross-tenant | AD-3 | `get_current_workspace_membership` → 404 « Workspace introuvable. » (`api/dependencies.py:40-56`), 403 réservé aux rôles ; `belongs_to_workspace` (`core/storage_keys.py:31`) ; `workspace_id ==` répété sur les requêtes |
| Sémantique de claiming / file parallèle | AD-4 | `claim_next_job` : QUEUED + `available_at` + tentatives + `FOR UPDATE SKIP LOCKED` (`workers/job_state.py:11-42`) ; heartbeat, `recover_stale_jobs` |
| Retries divergents | AD-5 | retry refuse `attempts >= max_attempts` (409), annulation seulement QUEUED (`api/routes/jobs.py:58-88`) ; `JobDeferred` (`workers/registry.py:10`) + `defer_job` qui restitue la tentative (`workers/job_state.py:115-136`) |
| Orchestrateur implicite web vs bot | AD-6 | aucun handler n'enfile l'étape suivante (grep négatif sur `workers/handlers/`) ; `video_id` requis hors INGEST (`api/schemas.py:192`) ; PROCESS réutilise les clips READY (`workers/handlers/process.py:48,105-111`) ; PUBLISH réconcilie par `external_id` (`workers/handlers/publish.py:61-81,292`) |
| Argent / fulfilment | AD-7 | `provider_price_mappings` (`api/models.py:655-658`) ; ledger append-only, solde = somme (`api/credit_service.py:58-60`) ; contraintes uniques d'idempotence sur 4 tables ; signature Dodo avant traitement (401 si invalide), MoneyFusion confirmé par `get_payment`, événements stockés puis 409 (`api/routes/billing.py:277-307`, `api/models.py:604`, `api/billing_service.py:312,324`) |
| Double stack OAuth | AD-8 | `SocialPublisher` + registre (`api/integrations/social.py:84,129`) ; Fernet `SOCIAL_CREDENTIALS_KEY` (`api/security/social_credentials.py`) ; serveur Flask :8420 (`bot/oauth_server.py`, `config.py:34`) ; `core/youtube_auth.py` / `core/youtube_uploader.py` présents |
| Configuration double | AD-9 | `api/config.py` pydantic avec validateurs durs en production ; `config.py` racine `mkdir` à l'import (crash latent `read_only` : `storage/processed` créé hors tmpfs) ; `JOB_*` racine morts (`workers/main.py` lit `api.config`) |
| Mélange de langues | AD-10 | messages d'erreur français constatés partout (`jobs.py`, `billing.py`, `job_state.py`) |

**Oubli — finding M1.** La stratégie fournisseur IA et e-mail est silencieuse (détail ci-dessous).

### 2. Chaque règle est enforceable et prévient sa divergence — oui, une nuance

Les 10 règles sont écrites en termes vérifiables (fonctions nommées, contraintes SQL, codes HTTP, interdits d'import) et chacune prévient effectivement la divergence qu'elle énonce — les ancres ci-dessus le prouvent. Le tableau de conventions est également ratifié : UUID PK, enums minuscules, `CheckConstraint`/`UniqueConstraint`, `X-Request-ID` via ContextVar (`api/observability.py:21,50,57`), `audit_events` (`api/models.py:217-220`), préfixes de clés `workspaces/{ws}/...` (`core/storage_keys.py:6-28`).

**Nuance — finding L3 :** AD-3 (« toute requête sur table possédée répète `workspace_id ==` ») reste purement disciplinaire : aucun garde mécanique n'est désigné (test, règle de lint, query de base). Vérifiable en revue de code, mais fragile à l'échelle.

### 3. Deferred — aucun élément ne permet une divergence ; une tension interne

Chaque item différé porte un porteur ou une condition de déclenchement, et l'état actuel reste une décision (personne ne peut diverger tant que la porte est fermée) :

- Auto-chaînage : AD-6 continue de lier toutes les unités ; la deferral n'ouvre rien.
- Expiration des crédits / remboursements : `CreditEntryType.EXPIRE` existe et n'est jamais écrit (vérifié) ; remboursement par portail Dodo sans dev (`decisions.md` §3). Pas de divergence possible.
- Routes partenaires : porte BMAD explicite ; `api/partner_service.py` existe, aucune route (vérifié).
- Observabilité : propriétaire nommé (Phase 7 de `docs/implementation-backend.md`, lignes 233-238 — réelles). Déférence légitime au niveau initiative.
- Rétention R2, pin des dépendances : conditions consignées dans `decisions.md` §3 et §5.
- **Tension — finding M2 :** le diagramme de topologie étiquette le worker « réplicable » alors que deux Deferred (fenêtre de double exécution PUBLISH, équité multi-worker) exigent explicitement un chantier *avant* tout scale-out. Un lecteur du seul diagramme pourrait répliquer les workers en croyant la topologie sûre.

### 4. Technologie nommée vérifiée courante — conforme

Toutes les lignes du tableau Stack correspondent exactement aux fichiers du dépôt :

- `python:3.11-slim-bookworm` (`Dockerfile:1`) ; ffmpeg apt (`Dockerfile:9`).
- fastapi ≥ 0.115.0, SQLAlchemy ≥ 2.0.32, psycopg[binary] ≥ 3.2.0, alembic ≥ 1.13.2, pydantic-settings ≥ 2.4.0, python-telegram-bot ≥ 21.0, boto3 ≥ 1.34.0, uvicorn ≥ 0.30.0 (`requirements.txt`).
- postgres:16-alpine, redis:7-alpine + appendonly (`docker-compose.yml:33,55,62`).
- Nginx + Certbot : templates `deploy/nginx/` + certbot installé par `scripts/configure-nginx.sh:105-112` (localisation à préciser, voir L1).
- CI/déploiement : tests + couverture, PostgreSQL 16 éphémère, intégration `tests.integration_workspace_postgres`, validation Compose (`ci.yml`), image SHA → GHCR, déploiement staging sur main (`deploy.yml`). Chaîne Alembic linéaire (17 migrations `20260813_0001..0017`).

Seule lacune : des lignes manquantes (fournisseurs IA/e-mail — M1).

### 5. Ratifie le brownfield — oui, à quelques imprécisions près

Aucune contradiction : chaque AD décrit le code tel qu'il est (voir tableau du point 1). Les quelques écarts factuels sont mineurs (findings L1 et L2) et ne portent que sur des labels de diagrammes ou de l'arbre source, jamais sur des règles.

### 6. Dimensions possédées par l'altitude — toutes décidées, différées ou ouvertes, sauf un sous-vide

- **Déploiement & environnements :** décidé et vérifié (topologie une image / rôles multiples ; dev override ; prod overlay `read_only` + tmpfs + `${VAR:?}` — `docker-compose.prod.yml:5-37` ; GHCR/SHA/staging — `deploy.yml`).
- **Infra / stratégie fournisseur :** décidé pour l'hébergement (VPS), l'image (GHCR), le stockage (R2), les paiements (Dodo + MoneyFusion), les réseaux sociaux (4 plateformes), Telegram. **Silencieux pour l'IA et l'e-mail** (M1).
- **Opérations :** explicitement différées avec porteur (Phase 7) — conforme au critère.
- **Données :** décidé (AD-1, conventions, ERD, migrations linéaires, métrologie `UsageEvent`).
- **Sécurité :** décidé (isolation AD-3, chiffrement Fernet AD-8, URL présignées, webhooks vérifiés, audit `audit_events`, durcissement conteneurs `no-new-privileges`/`cap_drop`/`read_only`, secrets `${VAR:?}`). Sauvegardes/restauration différées avec la Phase 7.
- **Intégration :** décidé pour social/paiements/Telegram/R2 ; partiellement silencieux sinon (M1).

Aucune dimension entière muette.

---

## Findings

### M1 — Stratégie fournisseur IA et e-mail silencieuse (moyen)

- **Localisation :** spine — section Stack (absence) et AD-9 ; code — `config.py:44` (`LLM_PROVIDER`, défaut `groq`), `core/llm_provider.py` (openai/gemini/groq/xai via base_url), `core/tts.py:16-17` (`Seul TTS_PROVIDER=openai est actuellement pris en charge`), `api/config.py:107-112` (`EMAIL_PROVIDER` log/resend).
- **Raisonnement :** le spine fixe les fournisseurs pour paiements, réseaux sociaux, stockage et bot, mais pas pour le LLM (multi-fournisseur commutable), le TTS (openai seul — contrainte cachée qui lèverait une `ValueError` à l'exécution) ni l'e-mail OTP. Or ces réglages vivent dans le `config.py` racine **gelé** (AD-9) : toute épic qui ajoute un fournisseur IA ou une voix doit soit étendre le config gelé (interdit par AD-9), soit migrer `core/llm_provider.py`/`core/tts.py` vers `api.config` — chantier dont le périmètre n'est pas listé dans la retraite AD-9. Deux unités could légitimement choisir des chemins différents. Remède simple : une ligne Stack + une phrase dans AD-9 définissant le chemin de migration des réglages IA (et une mention e-mail dans les conventions).

### M2 — « Worker réplicable » vs Deferred exigeant un chantier avant scale-out (moyen)

- **Localisation :** spine — Structural Seed (nœud `WK["worker — python -m workers.main (réplicable)"]`) contre Deferred « Fenêtre de double exécution PUBLISH … revisiter avant tout scale-out multi-worker » et « Équité multi-worker … à traiter avec la montée en charge ».
- **Raisonnement :** le diagramme, qui est ce qu'on regarde en premier, présente la réplication comme une capacité actuelle ; deux dettes différées conditionnent explicitement cette réplication (pas de clé d'idempotence fournisseur, écrasement inconditionnel d'`external_id` — ratifié par `workers/handlers/publish.py:292` ; pas de limite de concurrence par workspace ni d'index `(status, available_at)`). Tension interne : soit qualifier le nœud (« réplicable après chantiers différés »), soit sortir la condition du Deferred vers une note de topologie.

### L1 — Imprécisions factuelles mineures vs brownfield (bas)

- **Localisation :** diagramme de dépendance (nœud « api.services »), arbre source (« deploy/ — templates Nginx, scripts VPS »), conventions Stockage objets, diagramme de topologie (« une image, cinq services Compose »).
- **Raisonnement :** (a) il n'existe pas de paquet `api/services/` — les services sont des modules plats (`api/credit_service.py`, `billing_service.py`, `quota_service.py`, `partner_service.py`) ; (b) les scripts VPS (dont certbot) vivent dans `scripts/`, `deploy/` ne contient que `nginx/` ; (c) la convention de clés omet le préfixe `workspaces/{ws}/media-assets/...` qui existe (`core/storage_keys.py:14`, route `media_assets.py`) ; (d) le compose définit six services (postgres, redis, api, migrate, worker, shortpilot-bot), pas cinq. Aucun impact sur les règles — précision documentaire.

### L2 — État local du bot et arêtes bot→core absentes du diagramme (bas)

- **Localisation :** spine — Design Paradigm (« aucun processus ne détient d'état local durable ») et diagramme de dépendance ; code — `docker-compose.yml:111-119` (volumes `credentials:ro`, `bot_storage`, `bot_logs` ; bot sans `read_only` dans `docker-compose.prod.yml:33-37`), `bot/handlers.py:15` (`from core import youtube_auth`), `bot/upload_helpers.py:8` (importe des helpers privés de `core.video_processor`).
- **Raisonnement :** le paradigme est énoncé de façon absolue alors que le processus bot détient encore des volumes persistants et importe `core/` directement (dont le chemin OAuth legacy qu'AD-8 condamne — cohérent sur le fond, mais l'énoncé absolu du paradigme et le diagramme sans arête bot→core rendent la topo déclarative, non ratifiante). Suggestion : marquer l'arête bot→core en pointillé « legacy, retrait AD-8 » et qualifier le paradigme (« à l'exception du chemin OAuth legacy en cours de retrait »).

### L3 — AD-3 sans garde mécanique désignée (bas)

- **Localisation :** spine — AD-3 ; code — `api/dependencies.py` (aucun garde au-delà des dépendances de route), absence de test/lint cité.
- **Raisonnement :** la règle « toute requête sur table possédée répète `workspace_id ==` » est enforceable en revue mais aucun mécanisme (test de parcours des requêtes, règle de lint, repository pattern) n'est nommé pour la rendre durable. Une phrase désignant le garde (par ex. revue systématique + test d'intégration cross-tenant par nouvelle route possédée) suffirait.

---

## Annexe — éléments de preuve principaux

| Affirmation du spine | Preuve |
| --- | --- |
| `claim_next_job` FOR UPDATE SKIP LOCKED, QUEUED, `available_at`, tentatives | `workers/job_state.py:11-42` |
| `recover_stale_jobs` / heartbeat seuls mécanismes de reprise | `workers/job_state.py:45-67,139-169` |
| FAILED terminal, retry refusé, annulation QUEUED uniquement | `api/routes/jobs.py:58-88` |
| `JobDeferred` ne consomme pas de tentative | `workers/registry.py:10`, `workers/job_state.py:115-136` |
| `video_id` requis hors INGEST | `api/schemas.py:187-192` |
| Aucun handler n'enfile l'étape suivante | grep négatif `enqueue|create_job|notify_workers` sur `workers/handlers/` |
| PUBLISH réconcilie par `external_id` | `workers/handlers/publish.py:61-81,221,292` |
| Prix uniquement `provider_price_mappings` | `api/models.py:655-658` |
| Idempotence par contrainte unique (portée, clé) | `api/models.py:557,777,802,830` |
| Webhook vérifié avant fulfilment, 409 non corrélé stocké | `api/routes/billing.py:277-307`, `api/billing_service.py:291-324`, `api/models.py:604` |
| Fernet + `SOCIAL_CREDENTIALS_KEY` | `api/security/social_credentials.py:2-12` |
| Redis requis auth (OTP/OAuth/Telegram), fail-open ailleurs | `api/routes/auth.py:27-49`, `api/integrations/social_oauth.py:48-52`, `api/observability.py:90`, `workers/signals.py` |
| `config.py` racine : `mkdir` à l'import, `os.getenv`, gelé | `config.py:7-17`, `workers/main.py:4` (api.config) |
| Migration linéaire | `migrations/versions/20260813_0001..0017` |
| Environnements dev/prod/CI/GHCR/staging | `docker-compose.prod.yml`, `.github/workflows/ci.yml`, `.github/workflows/deploy.yml` |
| `CreditEntryType.EXPIRE` existe, jamais écrit | `api/models.py:712-719` + grep négatif |
| Routes partenaires absentes | `api/routes/` (aucun module partenaire), `api/partner_service.py` présent |
| Phase 7 = propriétaire observabilité | `docs/implementation-backend.md:233-238` |
