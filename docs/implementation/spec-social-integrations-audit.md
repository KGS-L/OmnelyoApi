---
title: 'Harden social integrations layer (AD-8) — Postiz-informed fixes'
type: 'bugfix'
created: '2026-08-16'
status: 'done'
review_loop_iteration: 0
baseline_commit: '89dd258b804fa63126dc9aa7d2ede212740a624f'
context:
  - '{project-root}/docs/planning/architecture/architecture-api-2026-08-16/ARCHITECTURE-SPINE.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The social integrations layer has one critical defect plus robustness gaps: Facebook/Instagram `exchange_code` derives Page tokens from the short-lived user token (connections silently die ~1–2 h after connect, and `expires_at=None` makes the worker refresh path unreachable), `/me/accounts` is unpaginated (grants silently truncated above the default page size), `InstagramPublisher.list_channels` always raises, token death is never surfaced (`SocialConnectionStatus.EXPIRED` / `ChannelStatus.DISCONNECTED` exist but are never written), there is no reactive refresh when a platform rejects a still-unexpired token mid-publish, and adapter registration is duplicated in two processes.

**Approach:** Fix adapters to Postiz-verified platform semantics (short→long-lived Meta exchange before Page-token derivation, cursor pagination, IG channel listing via Page-token `GET /me`), add one reactive refresh-and-retry step with quarantine (connection `EXPIRED`, channels `DISCONNECTED`) on refresh failure in the publish worker, disambiguate "adapter not configured" from "account not connected", and consolidate registration into one wiring function. No schema change; no new platform; no change to the legacy bot OAuth path.

## Boundaries & Constraints

**Always:**
- AD-8: tokens only in `SocialConnection` Fernet-encrypted fields; adapters stateless; secrets never logged; user-facing strings French (AD-10).
- Reactive refresh retries the provider call at most once; on refresh failure the original provider error is what gets persisted.
- Existing unittest style; commits `type(scope): summary` (English).

**Ask First:**
- Any schema/enum change (none planned), adding platforms or scopes, or touching the legacy bot OAuth path.

**Never:**
- Storing the Meta user-level token in `provider_metadata` (plaintext) or in files; the Page token remains the only stored credential.
- New dependencies; blocking sleeps beyond existing polling; auto-chaining of pipeline steps (AD-6).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Meta connect | OAuth code | Short token exchanged for long-lived user token BEFORE `/me/accounts`; Page tokens derived from long-lived token; grants keep `expires_at=None` | Exchange failure → AUTHORIZATION error |
| Many Pages | `/me/accounts` returns `paging.cursors.after` | Loop `limit=100` + `after` until exhausted, dedupe by page id | Network error mid-pagination → NETWORK retryable |
| IG channel refresh | stored Page token | `GET /me?fields=…,instagram_business_account{…}` returns the IG channel | Page without IG account → empty list |
| Publish with revoked-but-unexpired token | provider call raises AUTHORIZATION | Refresh credentials once, persist (Fernet), retry provider call once | Refresh failure → connection EXPIRED + channels DISCONNECTED, original error persisted |
| Unregistered adapter | `registry.get(missing)` | `PublisherNotRegisteredError` | Connect route → 503 « pas encore configurée » ; worker job fails with clear message |

</frozen-after-approval>

## Code Map

- `api/integrations/social.py` — `SocialPublisher` ABC (L84-126), `PublisherCredentials` (L55-60), registry (L129-151). Add `PublisherNotRegisteredError`, change `get()`.
- `api/integrations/facebook.py` — `exchange_code` (L55-91): add long-lived exchange + pagination. `_request` (L242-273): classification. `refresh_credentials` (L223-240): keep as repair path.
- `api/integrations/instagram.py` — `exchange_code` (L60-106): same Meta fixes. `list_channels` (L108-112): implement. `_request` (L254-279): classification.
- `api/integrations/tiktok.py` — `_request` (L137-155): classification (`access_token_invalid` → AUTHORIZATION, rate limits retryable). `refresh_credentials` (L126-135) rotation already correct — do not break.
- `api/integrations/default_publishers.py` — NEW: `register_default_publishers(settings, registry=social_publishers)`, idempotent via `has()`.
- `api/main.py` (L29-42) — replace inline registration block with the wiring call.
- `workers/handlers/publish.py` — drop `_register_publishers` (L144-166), call wiring; wrap `get_status` (L80) and `publish` (L128) with reactive refresh; quarantine helper; reuse `_persist_credentials` (L267-283).
- `api/routes/social_integrations.py` — `_publisher` (L50-54): translate `PublisherNotRegisteredError` → 503 « pas encore configurée ».
- `api/models.py` (L241-315) — read-only: `EXPIRED`/`DISCONNECTED` statuses already exist.
- `tests/test_facebook_publisher.py`, `tests/test_instagram_publisher.py`, `tests/test_tiktok_publisher.py`, `tests/test_social_publishers.py`, `tests/test_publish_handler.py` — suites to extend (they already mock `_request`/requests).

## Tasks & Acceptance

**Execution:**
- [x] `api/integrations/social.py` — add `PublisherNotRegisteredError(RuntimeError)`; `Registry.get` raises it (« La plateforme {x} n'est pas encore configurée. ») — disambiguates config vs connection.
- [x] `api/integrations/facebook.py` + `api/integrations/instagram.py` — in `exchange_code`: exchange short→long-lived user token (`grant_type=fb_exchange_token`) then call `/me/accounts` with it, paginating (`limit=100`, follow `paging.cursors.after`). Implement IG `list_channels` via `GET /me?fields=id,name,picture,instagram_business_account{id,username,name,profile_picture_url}`. Refine both `_request`: token errors (401/403, codes 190/102/10, subcode 33) → AUTHORIZATION; rate-limit codes (4/17/32/613) or 429 → TEMPORARY retryable.
- [x] `api/integrations/tiktok.py` — `_request`: `access_token_invalid`/`access_token_expired` → AUTHORIZATION; `rate_limit_exceeded`/429 → TEMPORARY retryable.
- [x] `api/integrations/default_publishers.py` — new single wiring; call from `api/main.py` and `workers/handlers/publish.py`.
- [x] `workers/handlers/publish.py` — reactive refresh wrapper: on AUTHORIZATION during `get_status`/`publish` (and on proactive-refresh failure), refresh once + persist + retry once; on refresh failure mark connection EXPIRED and its channels DISCONNECTED (own session, best-effort), then re-raise the original error.
- [x] tests — extend the five suites: long-lived-before-pages order, pagination, IG `list_channels`, not-registered error (incl. route 503 mapping), reactive refresh retry + quarantine, Meta/TikTok classification table.

**Acceptance Criteria:**
- Given a Meta connect, when `/me/accounts` is fetched, the request carries the long-lived user token and follows cursors until no `after` remains.
- Given an AUTHORIZATION failure during publish with refreshable credentials, when refresh succeeds, the provider call is retried exactly once and new tokens are persisted encrypted.
- Given refresh failure, the connection becomes EXPIRED, its channels DISCONNECTED, and the publication keeps the original provider error.
- Given a registry miss, `PublisherNotRegisteredError` reaches the connect route as 503 with the « pas encore configurée » message.

## Design Notes

- Postiz semantics adopted: Meta has no refresh grant — longevity comes from deriving Page tokens out of a long-lived user token at connect; `refresh_credentials` remains a repair path. TikTok rotates its refresh token each refresh (persisted); Google's refresh token is stable (old kept when the response omits it — existing `_persist_credentials` behavior, do not break).
- Audit accepted as-is (no task): YouTube per-publish channel ownership check (1 quota unit), TikTok single-chunk ≤64 Mo upload, Instagram synchronous container polling, PUBLISH double-execution window (already spine Deferred).
- Legacy bot OAuth path (Flask :8420, `core/youtube_auth.py`, `core/youtube_uploader.py`, dead bot handlers) violates AD-8 by existence; its retirement is a separate deliverable, deliberately out of scope here.

## Verification

**Commands:**
- `source .venv/bin/activate && python -m coverage run -m unittest discover -s tests && python -m coverage report` — all tests pass, coverage not regressed.
- `ruff check .` — clean.

## Suggested Review Order

**Meta token lifecycle (the critical fix)**

- Short-lived code token is exchanged for a long-lived user token BEFORE deriving Page tokens — the fix for connections dying in ~1–2 h.
  [`facebook.py:94`](../../api/integrations/facebook.py#L94)

- Same exchange for Instagram, plus cursor pagination of `/me/accounts` (limit 100, follow `paging.next`, dedupe by page id).
  [`instagram.py:106`](../../api/integrations/instagram.py#L106)

- Paginated Page discovery with repeated-cursor loop guard.
  [`facebook.py:113`](../../api/integrations/facebook.py#L113)

- Instagram channels are now listable from the stored Page token (`GET /me?fields=…,instagram_business_account{…}`); empty when the Page has no IG account.
  [`instagram.py:152`](../../api/integrations/instagram.py#L152)

**Worker refresh & quarantine**

- Refresh + persist serialized by a `FOR UPDATE` row lock on the connection; concurrent workers adopt the winner's credentials instead of clobbering (TikTok refresh-token rotation).
  [`publish.py:155`](../../workers/handlers/publish.py#L155)

- Reactive refresh: one refresh + one retry on AUTHORIZATION; second refusal after a successful refresh also quarantines.
  [`publish.py:221`](../../workers/handlers/publish.py#L221)

- Quarantine marks the connection EXPIRED and its channels DISCONNECTED, logs a warning, reserved for authorization failures only.
  [`publish.py:262`](../../workers/handlers/publish.py#L262)

- Entry point: handler wiring of proactive refresh, reconciliation and publish through the wrappers.
  [`publish.py:68`](../../workers/handlers/publish.py#L68)

**Contract & wiring**

- `PublisherNotRegisteredError` disambiguates "platform not configured" (503) from provider errors; `Registry.get` raises it.
  [`social.py:36`](../../api/integrations/social.py#L36)

- Single registration site shared by API and worker processes.
  [`default_publishers.py:11`](../../api/integrations/default_publishers.py#L11)

- API startup calls the shared wiring.
  [`main.py:24`](../../api/main.py#L24)

- Connect route maps the new error to 503 « pas encore configurée ».
  [`social_integrations.py:54`](../../api/routes/social_integrations.py#L54)

**Error classification**

- Meta: token errors (401/403, 190/102/10, subcode 33) vs rate limits (4/17/32/613, 429 retryable); string-error guard.
  [`facebook.py:280`](../../api/integrations/facebook.py#L280)

- TikTok: `access_token_invalid`/`access_token_expired` → AUTHORIZATION; rate limits retryable.
  [`tiktok.py:141`](../../api/integrations/tiktok.py#L141)

**Tests**

- Reactive refresh, quarantine conditions, locked refresh (persist/adopt), and a handler-level `publish_video` retry test.
  [`test_publish_handler.py:122`](../../tests/test_publish_handler.py#L122)

- Long-lived-before-pages order, pagination, IG `list_channels`, classification tables, wiring idempotence.
  [`test_instagram_publisher.py:46`](../../tests/test_instagram_publisher.py#L46)
