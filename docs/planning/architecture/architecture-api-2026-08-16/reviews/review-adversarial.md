# Revue adversariale — Architecture Spine (backend ShortPilot / Omnelyo)

| | |
|---|---|
| **Cible** | `docs/planning/architecture/architecture-api-2026-08-16/ARCHITECTURE-SPINE.md` (statut draft) |
| **Lentille** | Attaque adversariale : construire deux unités du niveau inférieur (épics/fonctionnalités) qui obéissent chacune à la lettre aux AD-1..AD-10 et pourtant se construisent de façon incompatible — formes de données partagées qui clashent, deux propriétaires pour une entité, chemins de mutation d'état concurrents. |
| **Date** | 2026-08-16 |
| **Verdict** | **pass-with-findings** — le paradigme et les dix AD tiennent les attaques frontales (seconde persistance, double stack OAuth, config double, filtre tenant) ; mais ils laissent ouvertes des collisions *transverses* entre épics, toutes situées du côté « qui écrit quel état, quand, et de façon unique ». Huit trous identifiés (4 élevées, 4 moyennes), chacun refermable par un AD serré ou nouveau. |
| **Ancrage** | Les attaques sont montées contre le spine, mais illustrées avec le code réel : `api/models.py`, `api/routes/{jobs,publications,videos,media_assets}.py`, `api/{credit_service,quota_service,billing_fulfillment}.py`, `api/integrations/telegram_jobs.py`, `workers/{job_state.py,handlers/{render,publish}.py}`. |

---

## F1 — Déclenchement programmé : deux propriétaires de la transition `SCHEDULED → PUBLISHING`

**Sévérité : Élevée.** Double publication réelle sur les réseaux + jobs fantômes FAILED terminaux.

**Unité A — Épic « calendrier / programmation des publications ».** Besoin : une publication `SCHEDULED` part toute seule à `scheduled_at`, sans POST client à l'instant T. Deux implémentations possibles, *toutes deux conformes* :
- (a) un worker ordonnanceur qui scanne `publications` (`status = SCHEDULED`, `scheduled_at <= now()`) et crée les jobs `PUBLISH` — conforme AD-1 (tout en base), AD-4 (c'est une ligne `jobs` claimée par `claim_next_job`), AD-6 (ce n'est pas un *handler* qui enchaîne l'étape suivante du pipeline ; AD-6 ne dit rien du temps).
- (b) enfilement immédiat avec `jobs.available_at = scheduled_at` — le champ existe déjà et `claim_next_job` respecte `available_at` : strictement conforme AD-4, sans une ligne de mécanisme nouveau.

**Unité B — Épic « flux Telegram v2 » (auto-publication après import).** Le bot crée le job `PUBLISH` au moment de l'import en passant `scheduled_at` au fournisseur (sémantique existante : ordonnancement *côté plateforme*, cf. `PublishRequest.scheduled_at` et `_persist_result` qui pose `SCHEDULED` chez le fournisseur). Conforme AD-4/AD-6/AD-8.

**La collision.**
1. *Deux sémantiques du même champ d'état.* Le chemin web actuel (`enqueue_batch_publication_records`, `api/routes/publications.py`) pose `publication.status = PUBLISHING` **dès l'enfilement**, même si la diffusion est dans 3 jours (le fournisseur détient l'horaire). Le chemin (b) ci-dessus laisse la ligne en `PUBLISHING` pendant des jours avec un job RUNNING jamais claimé ; le chemin (a) garde `SCHEDULED` puis bascule. Deux épics conformes produisent, pour la même table `publications`, deux significations opposées de `SCHEDULED`/`PUBLISHING` selon le point d'entrée (web, bot, ordonnanceur) — le calendrier de l'unité A devient ininterprétable.
2. *Deux producteurs de jobs PUBLISH pour une publication.* L'ordonnanceur (a) insère ses lignes `Job` directement (il n'est pas tenu de passer par `POST /v1/.../publications/{id}/publish`, que AD-6 réserve aux clients). Le garde-fou applicatif existant (`publication.job_id` + statut du job) vit uniquement dans la route ; l'ordonnanceur qui l'ignore crée un second job. `_load_context` (`workers/handlers/publish.py`) exige `Publication.job_id == job.id` : le job perdant lève `ValueError` à chaque tentative, brûle ses 10 `max_attempts`, et aboutit à **FAILED terminal et permanent** (AD-5) — un job fantôme impossible à rejouer, avec `publication.job_id` pointant vers l'autre job.
3. *Double publication.* Si les deux chemins publient réellement (ordonnanceur + fournisseur déjà programmé par le chemin B), le réseau reçoit deux posts. Le spine admet la fenêtre de double exécution PUBLISH mais seulement en Deferred « avant scale-out » ; ici la collision vient de la *conception des épics*, pas de la charge.

**Correctif proposé.** Serrer **AD-6** et ajouter un invariant : (i) un seul composant nommé est propriétaire du passage temps → file (choisir : ordonnanceur dédié OU `available_at` à l'enfilement — pas les deux) ; (ii) contrainte base de niveau AD : **au plus un job PUBLISH actif par publication** (index unique partiel ou `active_job_id` gardé sous verrou, comme le fait déjà le code applicatif des routes, mais promu en invariant) ; (iii) définir dans AD-6 la sémantique de `Publication.status` pendant l'attente (statut stable `SCHEDULED` tant que rien n'est parti chez le fournisseur).

---

## F2 — Deux clients-orchestrateurs = deux jobs RENDER = double débit de crédits

**Sévérité : Élevée.** Double facturation de crédits pour un seul clip, sans violation détectable d'aucun AD.

**Unité A — « frontend SaaS client »** avec avance automatique : à `job SUCCEEDED` de PROCESS, le front POSTe l'étape RENDER (exactement ce que AD-6 prescrit : « l'API est l'orchestrateur, le client POSTe chaque étape »).

**Unité B — « flux Telegram v2 »** qui enchaîne aussi côté bot (client légitime au sens d'AD-6, via les façades `api.*`).

**La collision.** `POST /v1/workspaces/{ws}/jobs` (`api/routes/jobs.py::create_job`) ne déduplique pas : il n'existe aucune contrainte « au plus un job actif par `(video_id, type)` » (contrairement aux publications, qui ont leur garde `publication.job_id`). Deux POST concurrents → deux lignes `jobs` RENDER. Chacun réserve 1 crédit (`CreditService.reserve(..., f"render-job:{job.id}")` — clé d'idempotence par job, donc deux réservations parfaitement conformes AD-7). Le handler RENDER court-circuite (« RENDER court-circuite si rendu existant » — exigé par AD-6) : le second job ne refait pas le travail… mais `complete_job` capture quand même sa réservation (`_resolve_render_credit(capture=True)`). Résultat : **2 crédits consommés, 1 rendu**. Chaque unité a obéi à AD-4, AD-6 et AD-7 à la lettre ; l'incompatibilité est dans leur *composition*.

**Correctif proposé.** Serrer **AD-6** : « l'enfileur déduplique : un au plus un job actif (QUEUED/RUNNING) par `(video_id, type)` ; l'endpoint retourne le job existant » — avec index unique partiel en base pour le rendre opposable, et non un garde applicatif. Complément AD-7 : une exécution court-circuitée (aucun travail produit) doit `release`, pas `capture`.

---

## F3 — `WorkspaceEntitlement` à deux plumes : doubles grants mensuels et période payée écrasée

**Sévérité : Élevée.** Intégrité monétaire : crédits doublés ou temps de abonnement perdu.

**Unité A — « activation facturation » (webhooks Dodo/MoneyFusion).** `BillingFulfillmentService.apply_payment` étend `WorkspaceEntitlement.period_end` depuis la période courante (`start = current_end if même plan et current_end > now`). Conforme AD-7 (prix serveur, ledger append-only, idempotence par `(provider, payment_id)`).

**Unité B — « dashboard programme partenaires »** (les modèles et le service existent déjà : `PartnerProfile`, `ReferralAttribution`, `partner_service.py` ; les routes sont explicitement en Deferred). Pour implémenter « mois offert / essai PRO au fillé », l'épic B écrit directement `WorkspaceEntitlement` (`plan_code`, `period_start = now`, `period_end = now+30j`) et grant via `CreditService.grant(..., "partner-gift:{id}")`. Conforme AD-7 : prix toujours serveur (pas d'argent), ledger append-only, clé d'idempotence unique.

**La collision.**
1. *Clé de grant mensuel frangible.* `CreditService.ensure_workspace` grant les crédits mensuels du plan avec la clé `monthly:{period_start.isoformat()}` — et `ensure_workspace` est appelé par **chaque lecture** de quota, de solde, de résumé. Quiconque déplace `period_start` fabrique une nouvelle clé : l'épic B déplace `period_start` → au prochain `ensure_workspace`, un grant `monthly:{nouveau}` s'ajoute au grant `monthly:{ancien}` encore non expiré. **Deux grants mensuels vivants en parallèle**, aucun ne violant la contrainte `(account_id, idempotency_key)`. Le solde étant « somme des écritures », l'inflation est invisible.
2. *Arithmétique de période dupliquée.* A étend depuis `period_end`, B écrit depuis `now`. B écrase : un utilisateur CREATOR avec 20 jours restants et 150 crédits non consommés reçoit `period_start = now` ; le webhook de renouvellement de A arrive ensuite et empile depuis la période du cadeau. Selon l'ordre d'arrivée : temps payé perdu ou temps doublé.

AD-7 gouverne l'idempotence *par opération* mais ne désigne **aucun propriétaire unique pour les transitions d'entitlement** — c'est le trou « two owners of one entity » classique.

**Correctif proposé.** Serrer **AD-7** : (i) `WorkspaceEntitlement` n'est écrit que par un seul service (fulfilment facturation) ; tout cadeau/essai/partenaire passe par un fulfilment typé (nouveau `ProductType` ou transition dédiée), jamais par écriture directe ; (ii) la clé du grant mensuel devient `(plan_code, period_start, period_end)` pour survivre aux disputes de calendrier ; (iii) l'algorithme d'extension de période est unique et versionné dans le spine (extension depuis `period_end`, toujours).

---

## F4 — `Job.status` à trois plumes : TOCTOU annulation vs claiming

**Sévérité : Moyenne à élevée** (fenêtre étroite aujourd'hui, élargie par tout scale-out).

**Unité A — « gestionnaire de jobs frontend »** : `POST /v1/.../jobs/{id}/cancel` et `/retry` (`api/routes/jobs.py`) mutent `Job.status` en lecture-modification-écriture **sans `with_for_update`** (idem `cancel_job_from_telegram` dans `api/integrations/telegram_jobs.py`). Conformes : AD-5 n'accepte l'annulation que QUEUED — c'est respecté.

**Unité B — « scale-out multi-workers »** : plus de workers, `recover_stale_jobs` plus fréquent. Conforme AD-4 (claiming exclusif via `claim_next_job`, `FOR UPDATE SKIP LOCKED`).

**La collision.** Séquence : la route lit `status = QUEUED` (sans verrou) → un worker claim (`RUNNING`, commit) → la route commite `CANCELLED` + `worker_id = NULL` par-dessus `RUNNING`. Le worker travaille encore : son `heartbeat_job` ne trouve plus de job `(RUNNING, worker_id)` → échec de lease → abandon en plein effet de bord (rendu FFmpeg interrompu, objet R2 partiel, publication laissée `PUBLISHING`). Même famille pour `retry` (remise QUEUED pendant un `recover_stale_jobs` concurrent) : le job peut être claimé deux fois via deux transitions licites distinctes. AD-4 définit la discipline du *claiming* mais pas celle des **autres transitions** ; la ligne « concurrence = verrous de lignes » vit dans les Consistency Conventions, non liée (« binds ») et sans module propriétaire désigné. Trois modules écrivent déjà `Job.status` (`workers/job_state.py`, `api/routes/jobs.py`, `api/integrations/telegram_jobs.py`) — c'est exactement la dérive que le spine devrait empêcher structurellement.

**Correctif proposé.** Serrer **AD-4** : « toute transition de `Job.status` (cancel, retry, recover, claim, complete, fail, defer) passe exclusivement par `workers/job_state.py` sous verrou de ligne ; routes et bot appellent ces fonctions, ne mutent jamais le statut ». Promouvoir au passage la convention verrous en règle liée.

---

## F5 — Bibliothèque médias vs rétention/quota : deux comptabilités du stockage, durée de vie ignore les publications programmées

**Sévérité : Moyenne** (contournement de quota déjà effectif dans le code ; échec de publications programmées à venir).

**Unité A — « bibliothèque médias (photos/carrousels, puis vidéos) »** : upload via `/media-assets/upload` (existant), tout en PostgreSQL (AD-1), clés R2 isolées par workspace (AD-3, `core/storage_keys.py::media_asset_key`).

**Unité B — « rétention R2 / nettoyage »** (Deferred pour les règles business) + « application stricte des quotas de stockage ».

**La collision.**
1. *Deux définitions de « stockage utilisé ».* `QuotaService.ensure_storage_available` ne somme que `Video.storage_size_bytes + rendered_size_bytes` — les `media_assets` (qui ont pourtant `size_bytes`) n'entrent jamais dans le « utilisé ». L'épic A appelle bien le quota à l'upload (conforme), mais chaque image est « gratuite » : un workspace sous plafond peut accumuler un volume illimité d'assets. L'épic B, lui, calculera le stockage réel (vidéos + assets) pour la rétention : les deux unités, chacune conforme à AD-1, affichent et enforcement deux nombres différents pour le même plan. Le spine n'érige aucune **autorité unique de comptabilité du stockage**.
2. *Durée de vie vs références.* `retention_expires_at` est un instantané pris à l'upload (`retention_deadline`). Une publication CAROUSEL programmée à J+25 sur un plan à rétention 14 jours référence des assets que l'épic B purgera à J+14 : l'enfilement échoue (« images introuvables », 409) ou le job PUBLISH meurt en FAILED terminal (AD-5). Aucun AD ne relie la durée de vie d'une ressource à l'horizon des publications qui la référencent.

**Correctif proposé.** Nouvel AD (stockage) : « une seule requête fait autorité pour l'usage stockage (vidéos + media_assets, une seule définition) ; toute écriture d'octets vers R2 passe par elle » et « `retention_expires_at = max(rétention du plan, horizon de la publication programmée la plus lointaine référençant la ressource) ». Les cycles de vie R2 restent en Deferred, mais l'autorité comptable doit être dans le spine dès maintenant — la bibliothèque médias, elle, existe déjà.

---

## F6 — Purge workspace (RGPD) vs records financiers : la suppression tenant casse sur `partner_commissions`

**Sévérité : Moyenne.**

**Unité A — « suppression de compte / purge RGPD »** : `DELETE` du workspace → cascades (`workspaces.id` en `ondelete=CASCADE` sur `payment_intents`, `subscriptions`, `credit_accounts`, etc.).

**Unité B — « programme partenaires »** : `PartnerCommission.payment_intent_id` et `PaymentFulfillment.payment_intent_id` sont en `ondelete=RESTRICT` (contraintes `uq_partner_commissions_payment`, FK RESTRICT) ; `ProviderEvent` n'a pas de FK workspace et survit.

**La collision.** Dès qu'une commission existe, la purge du workspace référencé échoue sur la FK RESTRICT (500 ou suppression partielle) ; si l'épic B « débloque » en rétrogradant les FK, le ledger de crédits et les fulfilments partent avec le workspace — destruction de records comptables légalement conservables. Les deux unités sont conformes (tout est PostgreSQL, argent idempotent, aucun AD ne parle de la **précédence rétention comptable vs suppression tenant**). AD-1 (« source de vérité ») est muet sur la survie des enregistrements financiers après la mort du tenant.

**Correctif proposé.** Nouvel AD : « les enregistrements financiers (`payment_intents`, `payment_fulfillments`, `provider_events`, `partner_commissions`, ledger) survivent à la suppression du workspace (tombstone / `workspace_id` NULL + archive) ; la purge tenant est un ordre de suppression défini (contenu, média, ledger non financier) ». À trancher avant l'épic partenaires, sinon l'épic B improvisera la politique fiscale.

---

## F7 — Complétude d'audit : la convention ne couvre que `/v1`, le bot et les workers mutent sans trace

**Sévérité : Moyenne** (faible en probabilité d'incident, élevée en exposition conformité).

**Unité A — « dashboard conformité/audit »** construit sur `audit_events` (append-only, `X-Request-ID`) en supposant l'exhaustivité des mutations métier — la convention dit « mutations `/v1` tracées dans `audit_events` », il la lit comme « les mutations sont tracées ».

**Unité B — « flux Telegram v2 » / workers** : `telegram_jobs.py` (création vidéo, annulation job) et les handlers (`_persist_result`, `_persist_credentials`, mutations de `publications`) écrivent l'état métier hors de tout middleware `/v1`, donc sans ligne d'audit. Conformes : rien dans AD-1..AD-10 n'exige l'audit hors `/v1`.

**La collision.** Le dashboard de A sous-rapporte systématiquement (publications annulées depuis Telegram, tokens rafraîchis, statuts modifiés par les workers). Deux unités conformes, données partagées (`audit_events`) à la sémantique divergente selon le processus écriturant.

**Correctif proposé.** Serrer la convention en règle liée : « toute mutation d'état métier, quel que soit le processus (route, bot, worker), écrit une trace `audit_events` (actor = utilisateur, worker ou bot) » — ou, si l'exhaustivité hors-`/v1` est jugée chère, l'inscrire explicitement comme périmètre réduit dans le spine pour que l'épic A ne construise pas sur une promesse inexistante.

---

## F8 — Unicité globale `channels (platform, external_id)` : le même compte distant ne peut pas vivre dans deux workspaces

**Sévérité : Moyenne.**

**Unité A — « nouvelle plateforme sociale (ex. LinkedIn) »** : ajoute l'enum, l'adaptateur `SocialPublisher`, l'enregistrement au registre — strictement conforme AD-8.

**Unité B — « mode agence / multi-workspaces »** (un utilisateur veut la même Page Facebook / le même compte TikTok dans deux workspaces, ou le partage d'un canal).

**La collision.** `uq_channels_platform_external_id` (`api/models.py`) est **globale** (sans `workspace_id`). Le second workspace connecte avec succès (`SocialConnection` est unique par `(workspace_id, platform, provider_account_id)`), mais l'upsert de `Channel` viole la contrainte globale. Le partage exigerait soit de dupliquer les lignes (impossible : contrainte), soit de déplacer le canal (interdit par AD-3 : « une ressource ne change jamais de workspace »). Aucun AD ne statuant « un compte distant appartient à au plus un workspace », l'épic B découvrira le mur en base, pas dans le spine — et le contournera peut-être en supprimant la contrainte silencieusement.

**Correctif proposé.** Décision à ériger en AD (via AD-3/AD-8) : soit « un compte distant = au plus un workspace » devient un invariant explicite (et l'épic B est refusé en amont), soit la contrainte devient `(workspace_id, platform, external_id)` avec un modèle de partage spécifié. C'est un choix produit, pas une conséquence technique : le spine doit le nommer.

---

## Synthèse

| # | Collision (unité A × unité B) | Entités/tables en clash | Sévérité | Correctif |
|---|---|---|---|---|
| F1 | Calendrier/programmation × auto-publish Telegram | `publications.status`, `jobs (PUBLISH)`, `available_at` | Élevée | Serrer AD-6 + invariant « un job PUBLISH actif par publication » + propriétaire unique du temps |
| F2 | Frontend orchestrateur × bot orchestrateur | `jobs (RENDER)`, `credit_reservations` | Élevée | Serrer AD-6 (dédup `(video_id, type)`) + AD-7 (court-circuit ⇒ release) |
| F3 | Activation facturation × dashboard partenaires | `workspace_entitlements`, `credit_ledger_entries` | Élevée | Serrer AD-7 : single-writer entitlement + clé de grant `(plan, période)` |
| F4 | Gestionnaire jobs frontend × scale-out workers | `jobs.status` (3 modules écrivains) | Moyenne-élevée | Serrer AD-4 : toutes les transitions via `workers/job_state.py` sous verrou |
| F5 | Bibliothèque médias × rétention/quota | `media_assets`, `videos.retention_expires_at`, usage stockage | Moyenne | Nouvel AD : autorité unique de comptabilité stockage + rétention ≥ horizon publications |
| F6 | Purge RGPD × programme partenaires | FK RESTRICT `partner_commissions`/`payment_fulfillments`, ledger | Moyenne | Nouvel AD : les records financiers survivent au tenant |
| F7 | Dashboard audit × flux Telegram/workers | `audit_events` (périmètre `/v1` seul) | Moyenne | Convention audit promue en règle liée (tout processus) ou périmètre déclaré |
| F8 | Nouvelle plateforme × multi-workspaces | `channels (platform, external_id)` unicité globale | Moyenne | Décision érigée en AD (unicité par workspace ou invariant un-compte-un-workspace) |

**Ce qui a résisté à l'attaque.** AD-1/2 (persistance unique, périmètre Redis), AD-8 (chemin social unique, contrat `SocialPublisher` + registre), AD-9 (config unique) et AD-3 (isolation tenant, 404/403, clés R2 revérifiées) n'ont pas pu être contournés par paires d'épics conformes — les trous sont tous du côté des **machines à états partagées** (`jobs.status`, `publications.status`, `workspace_entitlements`) et des **comptabilités implicites** (stockage, audit), domaines où le spine prescrit des *mécanismes* (claiming, ledger, idempotence) sans désigner de *propriétaire unique* ni d'invariants d'unicité d'état. Les items déjà en Deferred couvrent correctement la fenêtre de double exécution PUBLISH et l'équité multi-worker ; F1, F3 et F6 méritent en revanche de sortir du Deferred ou d'être refermés avant l'épic correspondant (calendrier, partenaires, RGPD).

**Recommandation de verdict : pass-with-findings.** Refermer F1–F4 (serrages d'AD peu coûteux, textuels) avant toute découpe en épics ; F5–F8 peuvent être traités comme décisions à inscrire au moment de l'épic concerné, sauf F6 à trancher avant le programme partenaires.
