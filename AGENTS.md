# AGENTS.md — Backend ShortPilot/Omnelyo

API FastAPI multi-tenant + workers + bot Telegram pour une plateforme SaaS de
création et publication de vidéos courtes. Python 3.11+, PostgreSQL 16,
Redis 7, Alembic. Le frontend vit dans un dépôt séparé.

## Carte du code

| Dossier | Rôle |
|---|---|
| `api/` | Socle SaaS partagé : app FastAPI, config, modèles, routes, auth, intégrations sociales, services (billing, crédits, quotas) |
| `workers/` | Processus worker autonome, file PostgreSQL durable (leases, heartbeat, retry) |
| `bot/` | Bot Telegram et serveur OAuth Flask |
| `core/` | Pipeline vidéo : yt-dlp, scènes, découpage, LLM, TTS, overlay, FFmpeg, R2 |
| `migrations/` | Alembic PostgreSQL |
| `db/`, `scheduler/`, `billing/` | Legacy SQLite — ne pas y ajouter de dépendance, voir `docs/decisions.md` |
| `docs/` | Documentation complémentaire et décisions en attente |

Deux points d'entrée : `api/main.py` (FastAPI, `/v1`) et `main.py` racine (bot).

## Commandes usuelles

```bash
# Environnement
source .venv/bin/activate

# Tests unitaires + couverture
python -m coverage run -m unittest discover -s tests
python -m coverage report

# Suite d'intégration (base PostgreSQL migrée requise)
python -B -m unittest tests.integration_workspace_postgres -v

# Migrations
alembic upgrade head            # URL lue depuis API_DATABASE_URL

# Stack locale
docker compose up -d --build

# Lint
ruff check .                     # config dans pyproject.toml
```

## Règles non négociables

- PostgreSQL est la source de vérité ; Redis ne stocke que du transitoire et
  doit rester optionnel (dégradation gracieuse).
- Ne jamais committer `.env`, `credentials/` ou des secrets ; les URLs R2 restent
  signées ; les prix viennent de `provider_price_mappings`, jamais du client.
- Toute modification de schéma passe par une migration Alembic dédiée.
- Ne pas étendre le legacy SQLite (`db/`, `scheduler/`, `billing/`) ;
  sa suppression est planifiée dans `docs/decisions.md`.
- Tests en style `unittest` ; les fichiers de test portent le préfixe `test_`,
  sauf `tests/integration_workspace_postgres.py` qui est invoquée explicitement
  par nom de module.
- Écrire la documentation et les messages de commit en français, comme le reste
  du dépôt.

## Documentation de référence

- `README.md` — installation, configuration, API, sécurité.
- `docs/implementation-backend.md` — feuille de route et état d'avancement.
- `docs/decisions.md` — décisions en attente (naming, legacy SQLite, facturation).
- `docs/ci-cd.md` — CI/CD, déploiement VPS, rollback.
