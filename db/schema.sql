-- Robot Short Yt — schéma DB (SQLite)

-- Une vidéo source soumise via le bot (lien YouTube envoyé)
CREATE TABLE IF NOT EXISTS source_videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_user_id INTEGER,
    telegram_chat_id INTEGER,
    source_type TEXT NOT NULL DEFAULT 'url', -- url | upload
    source_url TEXT NOT NULL,
    requested_publish_at TEXT,
    requested_title TEXT,
    local_path TEXT,
    submitted_at TEXT NOT NULL DEFAULT (datetime('now')),
    status TEXT NOT NULL DEFAULT 'pending',
        -- pending | downloading | cutting | publishing | done | partial | failed | cancelled
    error_message TEXT
);

-- Chaque clip généré à partir d'une vidéo source
CREATE TABLE IF NOT EXISTS clips (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_video_id INTEGER NOT NULL REFERENCES source_videos(id),
    sequence_order INTEGER NOT NULL,
    local_path TEXT,
    r2_url TEXT,
    duration_sec REAL,

    -- storytime / voix
    story_text TEXT,
    tts_audio_path TEXT,

    -- youtube
    youtube_video_id TEXT,
    youtube_title TEXT,
    scheduled_publish_at TEXT,   -- ISO 8601, dans le fuseau TIMEZONE
    status TEXT NOT NULL DEFAULT 'draft',
        -- draft | rendering | uploaded | scheduled | published | failed
    last_checked_at TEXT,

    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Log de toutes les notifications envoyées via le bot (traçabilité)
CREATE TABLE IF NOT EXISTS notifications_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    clip_id INTEGER REFERENCES clips(id),
    source_video_id INTEGER REFERENCES source_videos(id),
    message TEXT NOT NULL,
    level TEXT NOT NULL DEFAULT 'info',  -- info | warning | error
    sent_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- File persistante : un redémarrage ne perd pas les traitements en attente.
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_video_id INTEGER NOT NULL REFERENCES source_videos(id),
    job_type TEXT NOT NULL,                 -- process_url | publish_upload
    status TEXT NOT NULL DEFAULT 'queued', -- queued | running | completed | failed | cancelled
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 2,
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    started_at TEXT,
    finished_at TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Catalogue et comptabilité SaaS. workspace_id deviendra une FK PostgreSQL.
CREATE TABLE IF NOT EXISTS billing_plans (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    product_type TEXT NOT NULL, -- credits | subscription
    price_minor INTEGER NOT NULL CHECK(price_minor >= 0),
    currency TEXT NOT NULL,
    credits INTEGER NOT NULL DEFAULT 0,
    billing_interval TEXT,       -- month | year, NULL pour les crédits
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS billing_payments (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    plan_code TEXT NOT NULL REFERENCES billing_plans(code),
    provider TEXT NOT NULL,
    customer_email TEXT NOT NULL,
    external_reference TEXT,
    provider_reference TEXT,
    amount_minor INTEGER NOT NULL,
    currency TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    paid_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(provider, external_reference)
);

CREATE TABLE IF NOT EXISTS credit_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id TEXT NOT NULL,
    amount INTEGER NOT NULL,
    reason TEXT NOT NULL,
    payment_id TEXT UNIQUE REFERENCES billing_payments(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id TEXT NOT NULL UNIQUE,
    plan_code TEXT NOT NULL REFERENCES billing_plans(code),
    provider TEXT NOT NULL,
    external_reference TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    current_period_end TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS billing_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    event_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    processed_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(provider, event_id)
);

CREATE INDEX IF NOT EXISTS idx_clips_status ON clips(status);
CREATE INDEX IF NOT EXISTS idx_clips_scheduled ON clips(scheduled_publish_at);
CREATE INDEX IF NOT EXISTS idx_clips_source ON clips(source_video_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status_created ON jobs(status, created_at);
CREATE INDEX IF NOT EXISTS idx_jobs_source ON jobs(source_video_id);
CREATE INDEX IF NOT EXISTS idx_billing_payments_workspace ON billing_payments(workspace_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_billing_provider_reference_unique
ON billing_payments(provider, provider_reference) WHERE provider_reference IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_credit_ledger_workspace ON credit_ledger(workspace_id);
