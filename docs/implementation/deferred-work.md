# Deferred Work

- source_spec: `docs/implementation/spec-social-integrations-audit.md`
  summary: Extract a shared Meta base module for the duplicated Facebook/Instagram adapter code (`_request` classification, `_exchange_long_lived_token`, `_list_accounts`, error-code tables).
  evidence: The two adapters carry ~80 identical lines that already needed the same review fixes applied twice; the diff itself consolidated wiring into `default_publishers.py` but left the Meta duplication, which will drift on the next Graph API version bump.

- source_spec: `docs/implementation/spec-social-integrations-audit.md`
  summary: Propagate rate-limit backoff hints (HTTP `Retry-After`, Meta `x-business-use-case-usage`) from social adapters to job retry scheduling.
  evidence: Adapters now classify rate limits (Meta codes 4/17/32/613, TikTok `rate_limit_exceeded`) as retryable, but nothing downstream reads a delay, so retries run at the queue's default cadence.

- source_spec: `docs/implementation/spec-social-integrations-audit.md`
  summary: Make the worker retry policy consume the `SocialPublisherError.retryable` flag instead of attempt-count-only retries.
  evidence: Grep shows no consumer of `retryable` outside `api/integrations/`; non-retryable provider failures still burn job attempts, pre-dating this spec but now more granular classifications exist to exploit.
