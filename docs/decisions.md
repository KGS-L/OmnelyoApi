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

**Reste à faire (VPS)** : deux volumes concernés, `backend_bot_db` et
`omnelyo-backend_bot_db` (anciens noms de projet Compose). Après le déploiement
du retrait SQLite :

    docker run --rm -v backend_bot_db:/data alpine ls -laR /data
    docker run --rm -v omnelyo-backend_bot_db:/data alpine ls -laR /data
    docker volume rm api_bot_db

Le dernier (`api_bot_db`) est vide : créé par mégarde le 16 août par un
`docker run -v api_bot_db:...` sur un nom inexistant — Docker crée toujours le
volume demandé s'il manque. Après inspection, archiver si nécessaire puis
supprimer les deux volumes réels pour récupérer l'espace. Le rollback applicatif
du workflow GitHub Actions restaure l'image précédente si le nouveau bot se
comportait anormalement.

## 3. Facturation — décisions enregistrées le 16 août 2026, activation en attente des prix

Toute la chaîne technique existe (plans, ledger append-only, réservation de
crédits, checkout Dodo/MoneyFusion, webhooks vérifiés, fulfilment idempotent)
mais `BILLING_ENABLED=false` tant que la grille tarifaire n'est pas saisie.

**Décidé (16 août 2026)** :

- **Unité de crédit** : 1 crédit = 1 vidéo rendue — correspond à
  l'implémentation actuelle (réservation au `RENDER`, capture au succès,
  libération à l'échec).
- **Facturation des minutes** : oui, en plus des crédits. Le metering des
  minutes source, destinations et octets existe déjà (`UsageEvent`) ; la
  tarification reste à définir.
- **Publications auto-générées par IA** : facturation prévue plus tard, à
  concevoir quand la fonctionnalité existera.
- **Remboursements** : via le portail Dodo
  (`POST /v1/workspaces/{id}/billing/portal`), aucun développement spécifique.
- **Programme partenaires : activé** en décision. Paramètres (hypothèses à
  confirmer au contrat, cf. `PARTNER_PROGRAM.md` privé) : remise client de
  10 % sur Creator/Pro, commission partenaire de 20 % du revenu net, paiements
  après un délai de sécurité de 30 jours. État du code : service, modèles et
  application des codes promo existent (`api/partner_service.py`), mais
  **aucune route partenaire n'est exposée** (inscription, tableau de bord,
  attribution, paiements) — chantier à spécifier avec BMAD.
- **Rétention R2 (proposition en attente de validation)** : 90 jours pour le
  plan FREE, illimitée pendant l'abonnement actif, purge 30 jours après
  résiliation, suppression immédiate à la demande. Les clés de stockage étant
  déjà isolées par workspace, des règles de cycle de vie R2 par préfixe
  peuvent automatiser la purge sans code applicatif.

**Reste à décider** : les prix des plans (seul point bloquant pour passer
`BILLING_ENABLED=true`), la tarification des minutes, la confirmation définitive
des taux partenaires. Les documents privés `BUSINESS_MODEL.md` et
`PARTNER_PROGRAM.md` vivent hors du dépôt, dans le dossier parent.

## 4. Licence — AJOUTÉE (16 août 2026)

MIT, au nom de KGS-L : fichier `LICENSE` à la racine, section Licence du README
alignée.

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
