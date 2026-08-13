# Trajectoire SaaS — Robot Short YT

## Objectif

Transformer le bot actuel en plateforme multi-tenant où chaque client connecte ses propres comptes, choisit ses fournisseurs IA, soumet des vidéos, suit les traitements et maîtrise sa consommation.

## Architecture cible

```text
Interface web / Bot Telegram
            |
        API backend
            |
   PostgreSQL + Redis
            |
       File de jobs
      /     |      \
download  render  publication
      \     |      /
        Stockage objet
```

### Services recommandés

- Frontend : Next.js ou React, avec tableau de bord responsive.
- API : FastAPI, adaptée au code Python existant et à OpenAPI.
- Authentification : fournisseur géré (Clerk, Auth0, Supabase Auth) ou sessions sécurisées internes.
- Base : PostgreSQL. SQLite convient au prototype, pas aux workers SaaS concurrents.
- Jobs : Celery/Dramatiq/RQ avec Redis, ou une file cloud. Chaque étape doit être rejouable et idempotente.
- Stockage : R2/S3 avec clés privées et URL signées, jamais l'endpoint S3 brut.
- Paiement : Stripe avec abonnements, quotas et suivi de consommation.
- Observabilité : Sentry, métriques de jobs, journaux structurés et identifiant de corrélation par traitement.

## Modèle multi-tenant minimal

- `users` : identité et préférences.
- `workspaces` : tenant facturable ; permet plus tard les équipes.
- `workspace_members` : rôles propriétaire, administrateur, membre.
- `provider_credentials` : clés API chiffrées par workspace et fournisseur.
- `youtube_connections` : jetons OAuth chiffrés, chaîne et état de connexion.
- `source_videos` : propriétaire, URL, état et paramètres.
- `jobs` / `job_steps` : progression, tentatives et erreurs.
- `clips` : artefacts, publication et coût.
- `usage_events` : secondes vidéo, tokens LLM, caractères TTS, stockage et uploads.
- `subscriptions` : plan, limites et état Stripe.

Toutes les requêtes doivent être filtrées par `workspace_id`. Les fichiers doivent suivre une clé du type `workspaces/<workspace_id>/jobs/<job_id>/...`.

## Gestion des clés API

Deux modèles peuvent coexister :

1. BYOK : le client fournit ses propres clés. C'est simple pour une version open source et réduit le risque financier.
2. Clés de la plateforme : le SaaS paie les fournisseurs et facture des crédits. L'expérience est meilleure, mais nécessite quotas stricts, mesure des coûts et protection anti-abus.

Les clés ne doivent jamais être renvoyées au navigateur après leur enregistrement. Elles doivent être chiffrées avec une clé maîtresse externe au dépôt (KMS/Vault), masquées dans les logs et révocables individuellement.

## Ordre de développement recommandé

### MVP SaaS

1. Extraire le pipeline dans des jobs persistants.
2. Passer à PostgreSQL et ajouter `workspace_id` partout.
3. Créer une API FastAPI et une authentification web.
4. Construire les pages connexion, nouveau projet, progression et historique.
5. Ajouter OAuth YouTube par utilisateur et stockage chiffré.
6. Ajouter quotas simples avant les paiements.

### Commercialisation

1. Stripe, plans et limites.
2. Mesure détaillée des coûts par fournisseur.
3. Reprise automatique, annulation et support des jobs.
4. Modération, validation des droits sur les contenus et procédure de retrait.
5. Sauvegardes, rétention, export/suppression des données et politique de confidentialité.

### Optimisation à l'échelle

1. Séparer les workers CPU/GPU des workers réseau.
2. Fusionner les passes ffmpeg pour limiter le réencodage.
3. Mettre en cache les métadonnées et empreintes de vidéos.
4. Autoscaler les workers selon la profondeur de file.
5. Introduire des limites de concurrence par plan et par workspace.

## Décision importante

L'interface web ne doit pas appeler directement le pipeline. Elle crée un job et retourne immédiatement son identifiant. Le navigateur suit ensuite la progression par polling, Server-Sent Events ou WebSocket. Cette séparation rend les traitements longs fiables malgré les fermetures d'onglet, redémarrages et montées en charge.
