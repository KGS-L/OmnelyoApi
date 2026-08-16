# Décisions en attente et dette assumée

Dernière analyse du dépôt : 16 août 2026.

Ce document consigne les points qui ne peuvent pas être corrigés par le code seul
soit parce qu'ils dépendent d'une décision externe (business, infrastructure,
renommage public), soit parce que leur traitement exige une migration validée.
Chaque entrée décrit l'état actuel, le risque et l'action de déclenchement.

## 1. Double nommage ShortPilot / Omnelyo — DÉCIDÉ (16 août 2026)

**Décision** : `shortpilot` reste le nom interne (code, variables
d'environnement, base et utilisateur de test CI, utilisateur du conteneur) ;
`omnelyo` est réservé aux artefacts publics (domaines, image conteneur, chemins
VPS, expériences utilisateur). Le dépôt GitHub conserve son nom
`KGS-L/shortpilot-platform-api` : le renommage n'apporterait qu'une redirection
cosmétique en cassant les clones existants.

Cartographie de référence :

| Élément | Valeur | Portée |
|---|---|---|
| Dépôt GitHub | `KGS-L/shortpilot-platform-api` | conservé (décision ci-dessus) |
| Image conteneur | `omnelyo-backend` | `docker-compose.yml`, workflows |
| Chemins VPS | `/home/admin/projects/omnelyo/backend` | `docs/ci-cd.md`, scripts |
| Domaines publics | `omnelyo.kgslab.com`, `api-omnelyo.kgslab.com`, `bot-omnelyo.kgslab.com` | DNS et Nginx |
| Base/ utilisateur PostgreSQL | `omnelyo` | `.env` VPS |
| Code et variables | `shortpilot_*` (bot, base de test CI, utilisateur conteneur) | code source |

## 2. Stack SQLite historique — RETIRÉE (16 août 2026)

**Exécuté** : audit des imports (seuls `main.py` et `tests/test_core.py`
dépendaient du legacy, aucun module actif de `api/`, `bot/`, `core/` ni
`workers/`), `runtime/db` local vide (aucune donnée à migrer), puis suppression
de `db/`, `scheduler/`, `billing/`, de l'amorçage SQLite dans `main.py`, de la
variable `DATABASE_PATH` (`config.py`, Compose, `.env.example`, Dockerfile) et
des tests dédiés au legacy. PostgreSQL est l'unique persistance métier.

**Reste à faire (VPS)** : vérifier le volume `runtime/` du VPS au prochain
déploiement — le retrait du code ne supprime aucun fichier de données. Si des
données SQLite de staging méritent d'être conservées, les archiver avant de
nettoyer le volume. Le rollback applicatif du workflow GitHub Actions restaure
l'image précédente si le nouveau bot se comportait anormalement.

## 3. Facturation complète mais désactivée

Toute la chaîne technique existe (plans, ledger append-only, réservation de
crédits, checkout Dodo/MoneyFusion, webhooks vérifiés, fulfilment idempotent)
mais `BILLING_ENABLED=false` tant que la grille commerciale n'est pas validée.

**Risque** : dérive entre le modèle technique et les décisions business
(unité de crédit, remboursements, quotas).
**Action de déclenchement** : atelier business model (voir
[implementation-backend.md](implementation-backend.md)) ; les documents privés
`BUSINESS_MODEL.md` et `PARTNER_PROGRAM.md` vivent hors du dépôt, dans le
dossier parent de la plateforme.

## 4. Licence absente

Aucun fichier `LICENSE` : le dépôt n'est pas légalement réutilisable en l'état.

**Action de déclenchement** : choix du titulaire et de la licence (MIT/Apache-2.0
pour une ouverture maximale) avant toute présentation publique comme open source.

## 5. Dettes opérationnelles connues

- **Métriques, alertes, rétention et sauvegardes testées** : non réalisées ;
  le suivi reste dans [implementation-backend.md](implementation-backend.md).
- **`runtime/` possédé par root** en local (résidu d'exécution Docker) :
  `sudo chown -R $USER: runtime/` pour nettoyer ; le dossier est ignoré par Git.
- **`alembic.ini`** ne porte plus qu'une URL factice : la vraie URL vient
  toujours de `API_DATABASE_URL` via `migrations/env.py`.
- **Versions des dépendances** : `requirements.txt` fixe des bornes minimales ;
  les builds ne sont pas reproductibles bit à bit. Pinner (par exemple via un
  `requirements.lock` généré) le jour où une régression de build surviendra.
