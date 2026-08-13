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

CREATE INDEX IF NOT EXISTS idx_clips_status ON clips(status);
CREATE INDEX IF NOT EXISTS idx_clips_scheduled ON clips(scheduled_publish_at);
CREATE INDEX IF NOT EXISTS idx_clips_source ON clips(source_video_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status_created ON jobs(status, created_at);
CREATE INDEX IF NOT EXISTS idx_jobs_source ON jobs(source_video_id);
