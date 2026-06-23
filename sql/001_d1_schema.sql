CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    run_date TEXT NOT NULL,
    active_batch TEXT NOT NULL,
    source_count INTEGER NOT NULL DEFAULT 0,
    collected_count INTEGER NOT NULL DEFAULT 0,
    candidate_count INTEGER NOT NULL DEFAULT 0,
    proposal_count INTEGER NOT NULL DEFAULT 0,
    blocked_accounts_json TEXT NOT NULL DEFAULT '[]',
    warnings_json TEXT NOT NULL DEFAULT '[]',
    errors_json TEXT NOT NULL DEFAULT '[]',
    raw_archive_key TEXT NOT NULL DEFAULT '',
    doc_url TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'running',
    started_at TEXT NOT NULL,
    completed_at TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sources (
    source_key TEXT PRIMARY KEY,
    handle TEXT NOT NULL DEFAULT '',
    lookup_term TEXT NOT NULL DEFAULT '',
    company_name TEXT NOT NULL DEFAULT '',
    priority INTEGER NOT NULL DEFAULT 999,
    tier TEXT NOT NULL DEFAULT '',
    country TEXT NOT NULL DEFAULT '',
    category_fit_json TEXT NOT NULL DEFAULT '[]',
    frequency TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    batch TEXT NOT NULL DEFAULT '',
    last_fetched TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT '',
    comment TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS collected_posts (
    post_url TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    source_handle TEXT NOT NULL,
    published_at TEXT NOT NULL DEFAULT '',
    caption TEXT NOT NULL DEFAULT '',
    post_type TEXT NOT NULL DEFAULT '',
    media_urls_json TEXT NOT NULL DEFAULT '[]',
    hook_signal TEXT NOT NULL DEFAULT '',
    batch_date TEXT NOT NULL DEFAULT '',
    raw_archive_key TEXT NOT NULL DEFAULT '',
    instagram_post_id TEXT NOT NULL DEFAULT '',
    short_code TEXT NOT NULL DEFAULT '',
    owner_id TEXT NOT NULL DEFAULT '',
    owner_username TEXT NOT NULL DEFAULT '',
    owner_full_name TEXT NOT NULL DEFAULT '',
    likes_count INTEGER NOT NULL DEFAULT 0,
    comments_count INTEGER NOT NULL DEFAULT 0,
    is_comments_disabled INTEGER NOT NULL DEFAULT 0,
    hashtags_json TEXT NOT NULL DEFAULT '[]',
    dimensions_width INTEGER,
    dimensions_height INTEGER,
    engagement_count INTEGER NOT NULL DEFAULT 0,
    caption_length INTEGER NOT NULL DEFAULT 0,
    hashtag_count INTEGER NOT NULL DEFAULT 0,
    published_age_hours_at_collect INTEGER,
    caption_first_line TEXT NOT NULL DEFAULT '',
    has_cta INTEGER NOT NULL DEFAULT 0,
    has_question INTEGER NOT NULL DEFAULT 0,
    has_emoji INTEGER NOT NULL DEFAULT 0,
    is_image INTEGER NOT NULL DEFAULT 0,
    is_carousel INTEGER NOT NULL DEFAULT 0,
    is_video INTEGER NOT NULL DEFAULT 0,
    ingested_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_collected_posts_run_id ON collected_posts(run_id);
CREATE INDEX IF NOT EXISTS idx_collected_posts_source_handle ON collected_posts(source_handle);

CREATE TABLE IF NOT EXISTS candidates (
    candidate_key TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    post_url TEXT NOT NULL,
    source_handle TEXT NOT NULL,
    faiv_fit INTEGER NOT NULL,
    lead_potential INTEGER NOT NULL,
    hook_strength INTEGER NOT NULL,
    visual_transferability INTEGER NOT NULL,
    novelty INTEGER NOT NULL,
    total_score INTEGER NOT NULL,
    faiv_content_category TEXT NOT NULL DEFAULT '',
    service_area TEXT NOT NULL DEFAULT '',
    why_it_works TEXT NOT NULL DEFAULT '',
    originality_risk TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE(run_id, post_url)
);

CREATE INDEX IF NOT EXISTS idx_candidates_run_total ON candidates(run_id, total_score DESC);

CREATE TABLE IF NOT EXISTS proposals (
    proposal_key TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    post_url TEXT NOT NULL,
    source_handle TEXT NOT NULL,
    hook TEXT NOT NULL DEFAULT '',
    caption TEXT NOT NULL DEFAULT '',
    cta TEXT NOT NULL DEFAULT '',
    format TEXT NOT NULL DEFAULT '',
    image_brief TEXT NOT NULL DEFAULT '',
    recommended_asset_folder TEXT NOT NULL DEFAULT '',
    fallback_image_prompt TEXT NOT NULL DEFAULT '',
    why_selected TEXT NOT NULL DEFAULT '',
    faiv_content_category TEXT NOT NULL DEFAULT '',
    service_area TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'needs_edit',
    drive_folder_url TEXT NOT NULL DEFAULT '',
    approved INTEGER NOT NULL DEFAULT 0,
    used INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    UNIQUE(run_id, post_url)
);

CREATE INDEX IF NOT EXISTS idx_proposals_run_id ON proposals(run_id);
