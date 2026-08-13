# Audit technique — ShortPilot Platform API

Date de l'analyse : 13 août 2026

## Résumé

Le projet est bien découpé par responsabilités (`bot`, `core`, `scheduler`, `db`) et le pipeline est lisible. Il n'est toutefois pas encore fiable pour un usage réel, surtout en mode multi-utilisateur. Deux problèmes sont immédiatement bloquants : la génération LLM référence une constante inexistante, et l'identité de l'utilisateur Telegram est perdue avant l'upload YouTube. Plusieurs incohérences de dates, de concurrence et de cycle de vie des fichiers peuvent ensuite provoquer des publications sur le mauvais compte, au mauvais horaire, ou des enregistrements DB pointant vers des fichiers supprimés.

Priorité recommandée : corriger d'abord les éléments P0, ajouter des tests ciblés, puis sécuriser le pipeline et optimiser les traitements vidéo.

## Points positifs

- Architecture modulaire et noms de fonctions explicites.
- Requêtes SQL paramétrées, ce qui limite les injections SQL.
- Écriture atomique des jetons OAuth.
- Utilisation de `state` et expiration du flux OAuth.
- Commandes `ffmpeg` construites sous forme de listes, sans `shell=True`.
- Nettoyage des fichiers temporaires prévu dans le pipeline.
- Configuration centralisée et secrets principaux ignorés par Git.

## Problèmes critiques — P0

### 1. Le module storytime plante à chaque génération

`core/storytime.py` utilise `config.XAI_MODEL`, alors que `config.py` expose `GROQ_MODEL`. Le premier appel à `generate_story()` lève donc `AttributeError`.

Correction : utiliser `config.GROQ_MODEL`, valider la présence de la clé et du modèle au démarrage, puis harmoniser les commentaires qui parlent encore de Grok/xAI.

### 2. Le pipeline multi-utilisateur perd le propriétaire de la vidéo

`bot/handlers.py` connaît le `user_id`, mais `source_videos` ne possède aucune colonne correspondante. `scheduler.process_source_video()` ne peut donc pas savoir quel jeton OAuth employer et appelle les fonctions YouTube sans `user_id`. Elles cherchent alors le jeton générique `credentials/token.json`, tandis que la connexion Telegram a créé `credentials/youtube_<user_id>.json`.

Conséquences : upload impossible dans le cas courant, ou publication sur le mauvais compte si un ancien jeton générique existe. Le watchdog présente le même défaut.

Correction : ajouter `telegram_user_id` et idéalement `telegram_chat_id` à `source_videos`, propager cette valeur à l'upload, à la miniature, au watchdog, au calcul des créneaux et aux notifications.

### 3. L'heure locale est envoyée à YouTube comme si elle était en UTC

`get_next_available_slot()` produit un `datetime` dans `config.TIMEZONE`, mais `upload_scheduled_short()` le formate avec un suffixe `Z` sans le convertir en UTC. Exemple : `20:00+02:00` devient `20:00Z` au lieu de `18:00Z`.

Correction : convertir avec `publish_at.astimezone(timezone.utc)` avant de générer le timestamp RFC 3339.

### 4. Les chemins persistés désignent des fichiers supprimés

Le pipeline enregistre `local_path=final_clip_path` et `tts_audio_path`, puis ajoute ces deux fichiers à `clip_temp_files` et les supprime dans le `finally`. La DB contient donc des chemins invalides après chaque traitement réussi.

Correction : distinguer les artefacts temporaires des artefacts persistants. Conserver le clip final localement, ou mettre les colonnes locales à `NULL` après un archivage R2 vérifié. Ne pas persister le chemin TTS s'il doit être supprimé.

## Bugs importants — P1

### 5. Le plafond quotidien et le paramètre `user_id` ne sont pas appliqués

`get_remaining_slots(user_id)` ignore son argument, utilise l'heure UTC SQLite et compte tous les utilisateurs. `get_next_available_slot()` vérifie seulement qu'un créneau exact est libre ; il n'applique pas réellement `MAX_CLIPS_PER_DAY` par utilisateur.

Correction : filtrer par propriétaire et par journée dans le fuseau configuré. Ajouter une contrainte unique ou une réservation transactionnelle du créneau.

### 6. Course critique lors de la réservation des créneaux

Plusieurs `run_in_executor()` peuvent appeler simultanément `get_next_available_slot()`. Deux tâches peuvent voir le même créneau libre avant que l'une écrive en DB, puis programmer deux vidéos au même horaire.

Correction : réserver le créneau dans une transaction (`BEGIN IMMEDIATE`) et protéger l'unicité au niveau SQL. Un vrai worker à concurrence limitée serait plus robuste qu'un thread libre par message.

### 7. Une source est marquée `done` même si tous ses clips échouent

Après la boucle, le statut de la source passe toujours à `done`. Les erreurs de création de clips sont aussi seulement ignorées avec `continue`.

Correction : suivre les nombres de succès et d'échecs, puis produire un statut `done`, `partial` ou `failed` cohérent et enregistrer un résumé d'erreur.

### 8. Les notifications sont envoyées uniquement à l'administrateur

Le demandeur reçoit seulement l'accusé de réception. Toute la progression et les erreurs du pipeline partent vers `TELEGRAM_ADMIN_CHAT_ID`, ce qui contredit le message « Tu seras notifié » et empêche le vrai multi-utilisateur.

Correction : notifier le `chat_id` propriétaire ; réserver les alertes globales et techniques à l'administrateur.

### 9. Le watchdog utilise le mauvais compte YouTube

Il appelle `check_publish_status(yt_video_id)` sans propriétaire. Il ne peut donc pas vérifier les vidéos associées aux jetons individuels.

Correction : joindre `clips` à `source_videos`, récupérer le propriétaire et transmettre son `user_id`.

### 10. Les plages de scènes ne garantissent pas la durée minimale

`merge_scenes_to_clip_ranges()` fusionne tant que le maximum n'est pas dépassé, mais conserve des plages finales plus courtes que `min_duration`. Lors du découpage d'une longue scène, la logique peut aussi produire une plage supérieure à `max_duration` en absorbant un reste trop court.

Correction : définir explicitement la politique pour les restes (fusion avec le segment précédent, rejet, ou redistribution) et tester les cas limites.

### 11. La durée audio/vidéo finale est imprévisible

`overlay_card_on_video()` utilise `-shortest`. Si le TTS est trop court, la vidéo est raccourcie ; s'il est trop long, le récit est coupé à la fin de la vidéo. Le nombre de mots n'est qu'une estimation.

Correction : mesurer la durée audio avec `ffprobe`, puis ajuster la vidéo (boucle, vitesse ou durée cible) ou régénérer le texte/TTS selon une tolérance définie.

### 12. Validation d'entrée insuffisante

Tout texte commençant par HTTP(S) est accepté. Il n'y a ni limite de taille/durée, ni liste de plateformes, ni quota utilisateur, ni protection contre les soumissions répétées. Le téléchargement peut saturer CPU, disque et bande passante.

Correction : valider l'URL et le domaine, extraire les métadonnées avant téléchargement, imposer durée/taille maximales, quotas et nombre de jobs concurrents.

## Fiabilité et sécurité — P2

### 13. Configuration validée trop tard

Une clé Telegram vide, un URI OAuth vide, des créneaux invalides ou un modèle Groq absent ne sont détectés qu'en cours d'exécution. Certains `int(os.getenv(...))` peuvent aussi faire échouer l'import avec un message peu clair.

Correction : créer une fonction `validate_config()` appelée au démarrage avec des messages précis et sans afficher les secrets.

### 14. État OAuth seulement en mémoire

Les `state` sont perdus au redémarrage et ne fonctionnent pas avec plusieurs instances. Les entrées expirées non utilisées ne sont jamais purgées. L'accès au dictionnaire partagé n'est pas explicitement verrouillé.

Correction : pour une instance, ajouter verrou et purge périodique ; pour plusieurs instances, stocker les états dans Redis ou en DB avec expiration.

### 15. Révocation incomplète

`/disconnect` supprime seulement le fichier local sans révoquer le jeton auprès de Google, contrairement à ce qu'un utilisateur peut comprendre par « déconnecter ».

Correction : appeler l'endpoint de révocation Google puis supprimer localement, avec une stratégie claire si l'appel distant échoue.

### 16. HTML non échappé dans les messages et pages d'erreur

Des messages d'exception sont injectés dans des réponses Telegram en mode HTML et le paramètre OAuth `error` est inséré dans une page HTML. Cela peut casser le rendu et ouvre une possibilité d'injection de balises.

Correction : échapper avec `html.escape()` et ne jamais exposer directement les détails techniques aux utilisateurs.

### 17. SQLite n'est pas préparé à la concurrence

Les multiples threads ouvrent des connexions concurrentes sans `busy_timeout`, mode WAL, gestion centralisée des transactions ou clés étrangères activées. Des erreurs `database is locked` sont probables sous charge.

Correction : activer `PRAGMA foreign_keys=ON`, `journal_mode=WAL`, définir un timeout, et sérialiser les réservations sensibles.

### 18. Le serveur Flask de développement est utilisé en production

`app.run()` n'est pas un serveur WSGI de production, même derrière Caddy.

Correction : utiliser Gunicorn/Waitress, ou isoler le callback dans un service web adapté.

### 19. URL R2 probablement non publique

L'endpoint API S3 construit dans `storage_r2.py` n'est généralement pas une URL publique de consultation. La valeur stockée peut donc être inutilisable par un navigateur.

Correction : ajouter une variable `R2_PUBLIC_BASE_URL`, ou stocker uniquement la clé objet et générer une URL signée quand nécessaire.

### 20. Gestion d'erreurs trop large

Plusieurs `except Exception` masquent la cause ou retournent une valeur optimiste. Exemple : une erreur DB dans `get_remaining_slots()` retourne tous les créneaux disponibles.

Correction : capturer les exceptions attendues, journaliser avec contexte et adopter un comportement conservateur en cas d'échec.

## Optimisations — P3

### Pipeline vidéo

- Le clip est réencodé trois fois : découpage, conversion 9:16, puis overlay. Fusionner les filtres ffmpeg réduirait fortement le temps CPU et la perte de qualité.
- `video_processor.py` calcule `crop_filter`, mais ne l'utilise jamais. Le code et les commentaires promettent un fond flou alors que le rendu applique des bandes noires.
- Le Dockerfile installe Chromium/Playwright alors que l'overlay actuel utilise Pillow. Cela augmente beaucoup le temps de build et la taille de l'image.
- `moviepy`, `ffmpeg-python`, `SQLAlchemy`, `elevenlabs` et potentiellement Playwright semblent inutilisés directement. Retirer les dépendances inutiles réduira la surface de panne.
- Le client boto3 peut être réutilisé plutôt que recréé à chaque clip.

### Base et ordonnancement

- Ajouter une contrainte unique sur `(source_video_id, sequence_order)`.
- Indexer le propriétaire et les recherches combinées `(status, scheduled_publish_at)`.
- Éviter les comparaisons lexicales ambiguës de dates ; stocker toutes les dates en UTC, puis convertir uniquement pour l'affichage.
- Le scheduler APScheduler est stocké dans une variable locale. Conserver sa référence facilite l'arrêt propre et les tests.

### Qualité du code

- Remplacer les imports internes à certaines fonctions par des imports explicites lorsque les cycles sont supprimés.
- Uniformiser la langue et les noms Groq/Grok/xAI dans le code et le README.
- Retirer les variables inutilisées (`state`, `today_str`, plusieurs variables d'exception).
- Ajouter des types aux helpers internes de rendu et aux callbacks.

## Tests manquants à ajouter en premier

1. Tests unitaires de `merge_scenes_to_clip_ranges()` : vidéo courte, scène longue, reste court, trous entre scènes et limites exactes.
2. Tests de calcul des créneaux : fuseaux, changement de jour, heure d'été, plafond quotidien et concurrence.
3. Test d'intégration du chemin `user_id` : Telegram → DB → upload → watchdog → notification.
4. Tests OAuth : state inconnu, expiré, réutilisé et utilisateur incohérent.
5. Tests du pipeline avec APIs et subprocess mockés : succès, échec par étape, succès partiel et nettoyage.
6. Test de migration d'une base existante vers le nouveau schéma.

## Ordre de correction proposé

### Phase 1 — Rendre le flux fonctionnel

1. Corriger `GROQ_MODEL`.
2. Ajouter le propriétaire en DB et le propager partout.
3. Corriger la conversion UTC de `publishAt`.
4. Corriger les fichiers persistés puis supprimés.
5. Corriger le statut final d'une source.

### Phase 2 — Rendre l'ordonnancement fiable

1. Stocker les timestamps en UTC.
2. Réserver les créneaux transactionnellement et par utilisateur.
3. Configurer SQLite pour la concurrence.
4. Limiter le nombre de pipelines simultanés et permettre leur reprise après redémarrage.

### Phase 3 — Sécuriser

1. Valider configuration et URLs.
2. Échapper les sorties HTML et masquer les erreurs internes.
3. Durcir OAuth et la révocation.
4. Ajouter quotas, limites de taille/durée et timeouts subprocess/API.

### Phase 4 — Optimiser et tester

1. Fusionner les passes ffmpeg.
2. Nettoyer les dépendances et l'image Docker.
3. Ajouter les tests unitaires et d'intégration listés ci-dessus.
4. Ajouter lint, formatage, analyse statique et tests dans une CI.

## Vérifications effectuées

- Lecture de l'ensemble des fichiers Python, SQL, Docker et de configuration du dépôt.
- Vérification des références croisées de configuration et de `user_id`.
- Compilation Python tentée avec `python3 -m compileall -q .` : elle a été interrompue uniquement par des permissions sur `db/__pycache__` créé par un autre utilisateur/conteneur. Aucun échec de syntaxe n'a été signalé dans les autres modules.
- Aucun test automatisé n'est actuellement présent dans le dépôt.

## Prochaine étape recommandée

Commencer par la Phase 1 dans une modification cohérente comprenant une migration SQLite et des tests de non-régression. C'est le plus petit ensemble qui transforme le pipeline actuel en flux réellement utilisable sans publier sur le mauvais compte ni à la mauvaise heure.
