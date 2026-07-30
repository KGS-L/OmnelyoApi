-- Robot Short Yt — schéma DB (SQLite)

-- Une vidéo source soumise via le bot (lien YouTube envoyé)
CREATE TABLE IF NOT EXISTS source_videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_url TEXT NOT NULL,
    local_path TEXT,
    submitted_at TEXT NOT NULL DEFAULT (datetime('now')),
    status TEXT NOT NULL DEFAULT 'pending',
        -- pending | downloading | cutting | done | failed
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

CREATE INDEX IF NOT EXISTS idx_clips_status ON clips(status);
CREATE INDEX IF NOT EXISTS idx_clips_scheduled ON clips(scheduled_publish_at);
CREATE INDEX IF NOT EXISTS idx_clips_source ON clips(source_video_id);
