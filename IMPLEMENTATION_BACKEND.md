# Suivi d'implémentation du backend ShortPilot

Ce document est la feuille de route de référence du backend. Une case ne doit être
cochée que lorsque le code, la migration, les tests et la documentation associés
sont terminés.

Dernière analyse du dépôt : 13 août 2026.

## 1. État réel du projet

### Déjà fonctionnel

- [x] Bot Telegram basé sur `python-telegram-bot`.
- [x] Réception d'une URL ou d'une vidéo envoyée au bot.
- [x] Validation des vidéos reçues depuis Telegram.
- [x] File de jobs persistante dans SQLite avec annulation et reprise.
- [x] Pipeline : téléchargement, détection de scènes, découpage, storytime, TTS et overlay.
- [x] Archivage des rendus dans Cloudflare R2.
- [x] OAuth YouTube par utilisateur Telegram avec `state` anti-CSRF.
- [x] Upload, programmation et surveillance des publications YouTube.
- [x] API FastAPI et endpoint de santé.
- [x] Authentification web par OTP email et Google.
- [x] JWT d'accès et refresh tokens rotatifs/révocables.
- [x] Création automatique d'un workspace et d'un rôle `owner`.
- [x] Modèles PostgreSQL `Channel`, `Video`, `Job` et `Publication`.
- [x] Migration Alembic initiale pour l'identité et le multi-tenant.
- [x] Migration Alembic des ressources du pipeline.
- [x] Abstraction de paiement et validation manuelle idempotente dans SQLite.
- [x] Docker Compose, CI et configuration de déploiement.

### Partiellement réalisé

- [~] Multi-utilisateur : présent séparément côté web et Telegram, mais les deux identités ne sont pas liées.
- [~] Facturation : domaine et stockage SQLite présents, sans décision commerciale définitive ni routes web.
- [~] Multi-tenant : les nouveaux modèles ont un `workspace_id`, mais les dépendances d'autorisation ne sont pas encore écrites.
- [~] Chaînes sociales : modèle générique commencé, mais l'enum et l'intégration ne couvrent encore que YouTube.
- [~] Tests API : primitives de sécurité testées, mais pas encore de tests d'intégration PostgreSQL complets.

### Non réalisé

- [ ] API CRUD pour workspaces, chaînes, vidéos, jobs et publications.
- [ ] Liaison sécurisée compte web ↔ compte Telegram.
- [ ] Stockage PostgreSQL chiffré des connexions OAuth sociales.
- [ ] Migration du pipeline SQLite vers PostgreSQL et Redis.
- [ ] Workers indépendants de l'API et du bot.
- [ ] Publication TikTok, Facebook et Instagram.
- [ ] Fournisseur d'emails transactionnels.
- [ ] Observabilité, quotas, rétention et administration de production.

## 2. Décisions produit à prendre avant la facturation

Le code de crédits existant est un prototype technique. Aucun prix, unité de
crédit ou quota ne doit être considéré comme validé.

### Atelier business model obligatoire

- [ ] Définir la cible initiale : créateur individuel, agence, entreprise ou combinaison.
- [ ] Choisir entre abonnement, crédits à l'usage ou modèle hybride.
- [ ] Définir ce qu'un crédit paie : minute source, rendu, génération IA, publication ou bundle complet.
- [ ] Estimer le coût réel d'une vidéo : LLM, TTS, CPU, stockage, transfert et support.
- [ ] Définir marge cible, essai gratuit, expiration éventuelle et remboursement.
- [ ] Définir les limites par plan : workspaces, membres, chaînes, jobs simultanés et stockage.
- [ ] Choisir les devises et moyens de paiement prioritaires, notamment XOF et paiement international.
- [ ] Décider si les utilisateurs peuvent fournir leurs propres clés IA (BYOK).
- [ ] Documenter les règles de débit et de remboursement avant de créer les routes de paiement.

### Options à comparer

1. Abonnement simple : quota mensuel de vidéos et de chaînes.
2. Crédits : consommation variable selon la durée et les fonctions utilisées.
3. Hybride recommandé à évaluer : abonnement donnant des crédits mensuels, avec recharges ponctuelles.

### Travaux techniques après décision

- [ ] Migrer plans, paiements, ledger et abonnements de SQLite vers PostgreSQL.
- [ ] Ajouter un ledger immuable avec crédits positifs et débits négatifs.
- [ ] Réserver les crédits avant un job, puis régulariser selon le coût réel.
- [ ] Garantir l'idempotence des débits, remboursements et webhooks.
- [ ] Ajouter les routes de catalogue, solde, checkout et historique.
- [ ] Ajouter un fournisseur de paiement validé et ses webhooks signés.

## 3. Liaison du compte web à Telegram

### Expérience utilisateur retenue pour le MVP

ShortPilot exploite un bot partagé. L'utilisateur ne crée pas son propre bot : il
connecte son compte Telegram au compte ShortPilot déjà ouvert sur le web.

Instructions affichées dans l'interface :

1. Ouvrir **Paramètres → Intégrations → Telegram**.
2. Cliquer sur **Connecter Telegram**.
3. Ouvrir le lien proposé vers le bot officiel ShortPilot.
4. Appuyer sur **Démarrer** dans Telegram.
5. Revenir dans ShortPilot ; la connexion doit apparaître comme active.

### Flux technique

```text
Utilisateur web authentifié
    -> POST /v1/integrations/telegram/link
    -> jeton aléatoire, haché, à usage unique, expiration 10 minutes
    -> https://t.me/<bot>?start=link_<jeton>
    -> le bot reçoit /start link_<jeton>
    -> API interne consomme atomiquement le jeton
    -> associe telegram_user_id au User et au Workspace
    -> confirmation dans Telegram et dans l'interface web
```

### Implémentation et sécurité

- [x] Ajouter `TelegramConnection` avec `user_id`, `workspace_id`, `telegram_user_id`, `telegram_chat_id`, statut et dates.
- [x] Rendre `telegram_user_id` unique pour empêcher une liaison ambiguë.
- [x] Créer les jetons avec un générateur cryptographique et ne stocker que leur hash dans Redis.
- [x] Expiration de 10 minutes, usage unique et consommation atomique.
- [x] Ne jamais accepter directement un `user_id` ou `workspace_id` envoyé par Telegram.
- [x] Ajouter `POST /v1/workspaces/{workspace_id}/integrations/telegram/link`.
- [x] Ajouter `GET` et `DELETE /v1/workspaces/{workspace_id}/integrations/telegram`.
- [x] Adapter `/start` du bot pour traiter le paramètre `link_<jeton>`.
- [ ] Notifier les deux côtés après liaison ou déconnexion.
- [x] Permettre à l'utilisateur de révoquer Telegram depuis le web et depuis le bot.
- [ ] Faire créer tous les nouveaux jobs Telegram dans le même workspace PostgreSQL.
- [~] Tester rejeu, expiration et tentative de prise de contrôle ; test de concurrence Redis réel restant.

Une option « utiliser mon propre bot Telegram » pourra être étudiée plus tard ;
elle impose de stocker et faire tourner un token de bot par workspace et complexifie
fortement les webhooks, le support et la sécurité.

## 4. Publication multi-plateforme

Le choix appartient à l'utilisateur. Une même vidéo peut cibler une ou plusieurs
chaînes. Le backend crée une `Publication` indépendante par destination afin que
les statuts, erreurs, titres, horaires et nouvelles tentatives restent isolés.

### Faisabilité

| Plateforme | Publication API | Contraintes principales | Priorité proposée |
|---|---|---|---|
| YouTube | Déjà intégrée | Migrer les tokens fichier vers PostgreSQL chiffré | 1 |
| TikTok | Content Posting API | App et scope approuvés ; audit requis pour publier publiquement à grande échelle | 2 |
| Instagram | Instagram API | Compte professionnel et permission de publication ; média accessible par URL ou upload repris | 3 |
| Facebook | Graph API Reels Publishing | Publication vers une Page avec les permissions et tokens Meta adaptés | 3 |

### Évolution du domaine

- [ ] Étendre `ChannelPlatform` avec `TIKTOK`, `FACEBOOK` et `INSTAGRAM`.
- [ ] Remplacer les champs YouTube spécifiques du pipeline par des identifiants externes génériques.
- [ ] Ajouter un modèle `SocialConnection` ou `ProviderCredential` distinct de `Channel`.
- [ ] Chiffrer access tokens et refresh tokens avec une clé extérieure à la base.
- [ ] Stocker scopes, expiration, statut, date de dernière vérification et métadonnées minimales.
- [ ] Ne jamais exposer les tokens dans les réponses API ou les logs.
- [ ] Ajouter une contrainte garantissant que vidéo, chaîne, job et publication appartiennent au même workspace.
- [ ] Conserver une publication par destination, même lors d'une sélection multiple.

### Contrat commun des adaptateurs

- [ ] Définir `SocialPublisher.connect()` et le callback OAuth.
- [ ] Définir `list_channels()` pour laisser l'utilisateur choisir le compte ou la Page.
- [ ] Définir `validate_media()` avec les limites propres à chaque plateforme.
- [ ] Définir `publish()`, `get_status()`, `cancel()` et `refresh_credentials()`.
- [ ] Normaliser les erreurs : autorisation, validation, quota, modération, réseau et erreur temporaire.
- [ ] Préserver les réponses brutes utiles dans un champ JSON interne, sans secret.

### Expérience de création d'une publication

- [ ] L'utilisateur sélectionne YouTube, TikTok, Instagram et/ou Facebook.
- [ ] L'API vérifie que chaque destination est connectée et autorisée.
- [ ] L'utilisateur peut personnaliser légende, visibilité et horaire par plateforme.
- [ ] L'API valide le média et les options selon chaque destination avant facturation ou mise en file.
- [ ] Un job parent orchestre les rendus ; un job de publication séparé est créé par destination.
- [ ] Un échec sur une plateforme ne bloque pas les autres.

## 5. Ordre d'implémentation recommandé

### Phase 0 — Validation du socle actuel

- [x] Installer les dépendances de CI dans l'environnement de développement.
- [x] Appliquer toutes les migrations sur un PostgreSQL vierge.
- [x] Tester upgrade et downgrade Alembic.
- [x] Corriger les divergences éventuelles entre modèles et migrations.
- [ ] Ajouter une licence et vérifier les secrets dans l'historique Git.

### Phase 1 — Workspaces et autorisations

- [x] Retourner les workspaces accessibles avec `GET /v1/workspaces`.
- [x] Ajouter la dépendance `get_current_workspace_member`.
- [x] Appliquer les rôles `owner`, `admin` et `member`.
- [x] Ajouter des tests d'intégration d'isolation entre deux workspaces.
- [x] Ne jamais faire confiance à un `workspace_id` sans vérifier le membership.

### Phase 2 — API métier

- [x] Écrire les schémas Pydantic de `Channel`, `Video`, `Job` et `Publication`.
- [ ] Écrire repositories et services filtrés par workspace.
- [x] Ajouter CRUD, pagination, filtres et réponses d'erreur cohérentes.
- [ ] Ajouter upload vidéo par flux, limites de taille et validation MIME réelle.
- [ ] Utiliser des clés R2 `workspaces/<workspace_id>/jobs/<job_id>/...`.
- [ ] Ajouter URL signées, politiques de rétention et suppression.

### Phase 3 — Liaison Telegram

- [ ] Implémenter intégralement le flux décrit en section 3.
- [ ] Basculer les créations de vidéos et jobs du bot vers l'API métier.
- [ ] Maintenir temporairement un adaptateur de compatibilité SQLite si nécessaire.
- [ ] Retirer SQLite seulement après migration et validation des données historiques.

### Phase 4 — Workers et orchestration

- [ ] Choisir la file Redis : Dramatiq, Celery ou RQ.
- [ ] Sortir les traitements longs des processus API et Telegram.
- [ ] Rendre chaque étape idempotente et rejouable.
- [ ] Ajouter heartbeat, timeout, reprise, annulation et limite de concurrence par workspace.
- [ ] Émettre la progression par polling initialement, puis SSE si nécessaire.

### Phase 5 — Connecteurs sociaux

- [ ] Migrer YouTube vers le système générique de connexions.
- [ ] Livrer TikTok en environnement sandbox/non audité et préparer l'audit.
- [ ] Livrer Instagram pour comptes professionnels.
- [ ] Livrer Facebook pour Pages.
- [ ] Ajouter une matrice automatisée de validation des médias.
- [ ] Ajouter polling et webhooks de statut lorsque les plateformes les proposent.

### Phase 6 — Business model et paiement

- [ ] Organiser et valider l'atelier de la section 2.
- [ ] Implémenter le modèle retenu dans PostgreSQL.
- [ ] Ajouter quotas avant de permettre une utilisation publique.
- [ ] Activer paiements et webhooks seulement après tests d'idempotence et de sécurité.

### Phase 7 — Production

- [ ] Brancher un fournisseur d'emails transactionnels.
- [ ] Ajouter logs structurés, identifiant de corrélation, métriques et alertes.
- [ ] Ajouter rate limiting, audit log et administration sécurisée.
- [ ] Ajouter sauvegardes PostgreSQL/R2 et procédure de restauration testée.
- [ ] Définir rétention, export et suppression des données utilisateur.
- [ ] Faire valider conditions d'utilisation, confidentialité et droits sur les contenus.

## 6. Prochaine étape concrète

Commencer par la phase 0, puis la phase 1. La liaison Telegram et les connecteurs
sociaux dépendent d'une autorisation workspace fiable. Le business model reste un
jalon de décision séparé : son atelier doit avoir lieu avant toute implémentation
définitive des crédits et des paiements.
