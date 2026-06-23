from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class SourceAccount:
    priority: int
    tier: str
    company_name: str
    raw_lookup: str
    lookup_term: str
    country: str
    faiv_categories: list[str]
    frequency: str
    comment: str
    handle: str | None = None
    active: bool = True
    batch: str = ""
    last_fetched: str = ""
    status: str = "ok"


@dataclass(slots=True)
class CollectedPost:
    source_handle: str
    post_url: str
    published_at: str
    caption: str
    post_type: str
    media_urls: list[str]
    hook_signal: str
    batch_date: str
    raw_archive_key: str | None = None
    raw_payload: dict[str, Any] = field(default_factory=dict)
    run_id: str = ""
    instagram_post_id: str = ""
    short_code: str = ""
    owner_id: str = ""
    owner_username: str = ""
    owner_full_name: str = ""
    likes_count: int = 0
    comments_count: int = 0
    is_comments_disabled: bool = False
    hashtags: list[str] = field(default_factory=list)
    dimensions_width: int | None = None
    dimensions_height: int | None = None
    engagement_count: int = 0
    caption_length: int = 0
    hashtag_count: int = 0
    published_age_hours_at_collect: int | None = None
    caption_first_line: str = ""
    has_cta: bool = False
    has_question: bool = False
    has_emoji: bool = False
    is_image: bool = False
    is_carousel: bool = False
    is_video: bool = False


@dataclass(slots=True)
class CandidatePost:
    source_post: CollectedPost
    faiv_fit: int
    lead_potential: int
    hook_strength: int
    visual_transferability: int
    novelty: int
    total_score: int
    faiv_category: str
    why_it_works: str
    originality_risk: str


@dataclass(slots=True)
class Proposal:
    source_candidate: CandidatePost
    hook: str
    caption: str
    cta: str
    format: str
    image_brief: str
    recommended_asset_folder: str
    fallback_image_prompt: str
    why_selected: str


@dataclass(slots=True)
class AssetMatch:
    folder: str
    image_count: int
    confidence: str
    use_ai_prompt: bool


@dataclass(slots=True)
class RunSummary:
    run_date: str
    active_batch: str
    collected_count: int
    candidate_count: int
    proposal_count: int
    blocked_accounts: list[str]
    warnings: list[str]
    errors: list[str]
    run_id: str = ""
    source_count: int = 0
    raw_archive_key: str | None = None
    status: str = "completed"
    doc_url: str | None = None
