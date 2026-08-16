# Décisions en attente et dette assumée

Dernière analyse du dépôt : 16 août 2026.

Ce document consigne les points qui ne peuvent pas être corrigés par le code seul
soit parce qu'ils dépendent d'une décision externe (business, infrastructure,
renommage public), soit parce que leur traitement exige une migration validée.
Chaque entrée décrit l'état actuel, le risque et l'action de déclenchement.

## 1. Double nommage ShortPilot / Omnelyo

Le renommage produit vers **Omnelyo** est entamé mais inachevé. Cartographie
actuelle :

| Élément | Valeur | Portée |
|---|---|---|
| Dépôt GitHub | `KGS-L/shortpilot-platform-api` | renommage à décider côté GitHub |
| Image conteneur | `omnelyo-backend` | `docker-compose.yml`, workflows |
| Chemins VPS | `/home/admin/projects/omnelyo/backend` | `docs/ci-cd.md`, scripts |
| Domaines publics | `omnelyo.kgslab.com`, `api-omnelyo.kgslab.com`, `bot-omnelyo.kgslab.com` | DNS et Nginx |
| Base/ utilisateur PostgreSQL | `omnelyo` | `.env` VPS |
| Code et variables | `shortpilot_*` (bot, base de test CI, `SHORTPILOT` dans les settings) | code source |

**Risque** : confusion lors des recherches dans le code et les issues ;
documentation qui doit expliquer les deux noms.
**Action de déclenchement** : décider du nom définitif, renommer le dépôt GitHub
(redirection automatique), puis aligner le code en une seule passe.
**Décision minimale recommandée** : conserver `shortpilot` en interne (code,
variables) et réserver `omnelyo` aux artefacts publics (domaines, image, VPS),
puis l'écrire noir sur blanc ici.

## 2. Stack SQLite historique encore amorcée au démarrage du bot

`main.py` (point d'entrée du bot, service `shortpilot-bot` du Compose) appelle
encore `db.database.init_db` et démarre `scheduler.job_queue` + `scheduler.watchdog`
de l'ancien pipeline SQLite. Les handlers du bot (`bot/handlers.py`) écrivent
déjà dans PostgreSQL via `api.database`. L'ancienne file SQLite tourne donc à vide
à côté du worker PostgreSQL.

**Risque** : double exécution si un handler historique est réactivé ;
maintenance de deux modèles de données.
**Action de déclenchement** : auditer `runtime/db` (données historiques
éventuelles), migrer ou archiver, puis retirer l'amorçage SQLite de `main.py`
et supprimer `db/`, `scheduler/` et `billing/` (couche SQLite) dans le même
changemement. Voir la case dédiée dans
[implementation-backend.md](implementation-backend.md).
**En attendant** : ne pas ajouter de nouvelle dépendance à `db/` ni `scheduler/`.

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
