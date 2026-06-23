from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import requests

from src.collect import normalize_post_items
from src.config import AppConfig, ConfigError
from src.models import CandidatePost, CollectedPost, Proposal, SourceAccount


DEFAULT_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "sql" / "001_d1_schema.sql"
COLLECTED_POSTS_COLUMN_DEFS = {
    "instagram_post_id": "TEXT NOT NULL DEFAULT ''",
    "short_code": "TEXT NOT NULL DEFAULT ''",
    "owner_id": "TEXT NOT NULL DEFAULT ''",
    "owner_username": "TEXT NOT NULL DEFAULT ''",
    "owner_full_name": "TEXT NOT NULL DEFAULT ''",
    "likes_count": "INTEGER NOT NULL DEFAULT 0",
    "comments_count": "INTEGER NOT NULL DEFAULT 0",
    "is_comments_disabled": "INTEGER NOT NULL DEFAULT 0",
    "hashtags_json": "TEXT NOT NULL DEFAULT '[]'",
    "dimensions_width": "INTEGER",
    "dimensions_height": "INTEGER",
    "engagement_count": "INTEGER NOT NULL DEFAULT 0",
    "caption_length": "INTEGER NOT NULL DEFAULT 0",
    "hashtag_count": "INTEGER NOT NULL DEFAULT 0",
    "published_age_hours_at_collect": "INTEGER",
    "caption_first_line": "TEXT NOT NULL DEFAULT ''",
    "has_cta": "INTEGER NOT NULL DEFAULT 0",
    "has_question": "INTEGER NOT NULL DEFAULT 0",
    "has_emoji": "INTEGER NOT NULL DEFAULT 0",
    "is_image": "INTEGER NOT NULL DEFAULT 0",
    "is_carousel": "INTEGER NOT NULL DEFAULT 0",
    "is_video": "INTEGER NOT NULL DEFAULT 0",
}


@dataclass(slots=True)
class CloudflareD1Store:
    account_id: str
    api_token: str
    database_id: str
    session: requests.Session | None = None
    schema_path: Path = DEFAULT_SCHEMA_PATH

    def __post_init__(self) -> None:
        if self.session is None:
            self.session = requests.Session()

    def ensure_schema(self) -> None:
        schema_sql = self.schema_path.read_text(encoding="utf-8")
        self._execute_query(schema_sql)
        self._ensure_collected_posts_columns()
        self._ensure_candidates_columns()
        self._ensure_proposals_columns()

    def get_existing_post_urls(self, source_handles: Iterable[str] | None = None) -> set[str]:
        handles = [handle for handle in source_handles or [] if handle]
        if handles:
            placeholders = ", ".join("?" for _ in handles)
            sql = f"""
                SELECT post_url
                FROM collected_posts
                WHERE source_handle IN ({placeholders})
            """
            rows = self._execute_query(sql, handles)
        else:
            rows = self._execute_query("SELECT post_url FROM collected_posts")
        return {str(row["post_url"]) for row in rows if row.get("post_url")}

    def get_latest_post_dates(self, source_handles: Iterable[str] | None = None) -> dict[str, str]:
        handles = [handle for handle in source_handles or [] if handle]
        if handles:
            placeholders = ", ".join("?" for _ in handles)
            sql = f"""
                SELECT source_handle, MAX(published_at) AS latest
                FROM collected_posts
                WHERE source_handle IN ({placeholders})
                GROUP BY source_handle
            """
            rows = self._execute_query(sql, handles)
        else:
            rows = self._execute_query("SELECT source_handle, MAX(published_at) AS latest FROM collected_posts GROUP BY source_handle")
        return {str(row["source_handle"]).casefold(): str(row["latest"]) for row in rows if row.get("latest")}

    def upsert_sources(self, source_rows: list[dict[str, str]]) -> None:
        if not source_rows:
            return
        timestamp = utc_now_iso()
        batch = []
        for row in source_rows:
            source_key = row.get("handle") or row.get("lookup_term")
            if not source_key:
                continue
            batch.append(
                {
                    "sql": """
                        INSERT INTO sources (
                            source_key, handle, lookup_term, company_name, priority, tier, country,
                            category_fit_json, frequency, active, batch, last_fetched, status, comment, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(source_key) DO UPDATE SET
                            handle = excluded.handle,
                            lookup_term = excluded.lookup_term,
                            company_name = excluded.company_name,
                            priority = excluded.priority,
                            tier = excluded.tier,
                            country = excluded.country,
                            category_fit_json = excluded.category_fit_json,
                            frequency = excluded.frequency,
                            active = excluded.active,
                            batch = excluded.batch,
                            last_fetched = excluded.last_fetched,
                            status = excluded.status,
                            comment = excluded.comment,
                            updated_at = excluded.updated_at
                    """,
                    "params": [
                        source_key,
                        row.get("handle") or "",
                        row.get("lookup_term") or "",
                        row.get("company_name") or "",
                        int(row.get("priority", "999") or 999),
                        row.get("tier") or "",
                        row.get("country") or "",
                        json.dumps(split_csv(row.get("category_fit", "")), ensure_ascii=False),
                        row.get("frequency") or "",
                        1 if (row.get("active") or "").lower() == "yes" else 0,
                        row.get("batch") or "",
                        row.get("last_fetched") or "",
                        row.get("status") or "",
                        row.get("comment") or "",
                        timestamp,
                    ],
                }
            )
        self._execute_batch(batch)

    def record_run_start(
        self,
        *,
        run_id: str,
        run_date: str,
        active_batch: str,
        source_count: int,
        raw_archive_key: str | None,
    ) -> None:
        self._execute_query(
            """
                INSERT INTO runs (
                    run_id, run_date, active_batch, source_count, collected_count, candidate_count,
                    proposal_count, blocked_accounts_json, warnings_json, errors_json, raw_archive_key,
                    status, started_at, updated_at
                ) VALUES (?, ?, ?, ?, 0, 0, 0, '[]', '[]', '[]', ?, 'running', ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    run_date = excluded.run_date,
                    active_batch = excluded.active_batch,
                    source_count = excluded.source_count,
                    raw_archive_key = excluded.raw_archive_key,
                    status = excluded.status,
                    updated_at = excluded.updated_at
            """,
            [
                run_id,
                run_date,
                active_batch,
                source_count,
                raw_archive_key or "",
                utc_now_iso(),
                utc_now_iso(),
            ],
        )

    def update_run_summary(self, summary) -> None:
        self._execute_query(
            """
                UPDATE runs
                SET
                    collected_count = ?,
                    candidate_count = ?,
                    proposal_count = ?,
                    blocked_accounts_json = ?,
                    warnings_json = ?,
                    errors_json = ?,
                    raw_archive_key = ?,
                    doc_url = ?,
                    status = ?,
                    updated_at = ?,
                    completed_at = ?
                WHERE run_id = ?
            """,
            [
                summary.collected_count,
                summary.candidate_count,
                summary.proposal_count,
                json.dumps(summary.blocked_accounts, ensure_ascii=False),
                json.dumps(summary.warnings, ensure_ascii=False),
                json.dumps(summary.errors, ensure_ascii=False),
                summary.raw_archive_key or "",
                summary.doc_url or "",
                summary.status,
                utc_now_iso(),
                utc_now_iso(),
                summary.run_id,
            ],
        )

    def insert_collected_posts(self, posts: list[CollectedPost]) -> None:
        if not posts:
            return
        batch = []
        for post in posts:
            batch.append(
                {
                    "sql": """
                        INSERT INTO collected_posts (
                            post_url, run_id, source_handle, published_at, caption, post_type,
                            media_urls_json, hook_signal, batch_date, raw_archive_key,
                            instagram_post_id, short_code, owner_id, owner_username, owner_full_name,
                            likes_count, comments_count, is_comments_disabled, hashtags_json,
                            dimensions_width, dimensions_height, engagement_count, caption_length,
                            hashtag_count, published_age_hours_at_collect, caption_first_line,
                            has_cta, has_question, has_emoji, is_image, is_carousel, is_video,
                            ingested_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(post_url) DO UPDATE SET
                            run_id = excluded.run_id,
                            source_handle = excluded.source_handle,
                            published_at = excluded.published_at,
                            caption = excluded.caption,
                            post_type = excluded.post_type,
                            media_urls_json = excluded.media_urls_json,
                            hook_signal = excluded.hook_signal,
                            batch_date = excluded.batch_date,
                            raw_archive_key = excluded.raw_archive_key,
                            instagram_post_id = excluded.instagram_post_id,
                            short_code = excluded.short_code,
                            owner_id = excluded.owner_id,
                            owner_username = excluded.owner_username,
                            owner_full_name = excluded.owner_full_name,
                            likes_count = excluded.likes_count,
                            comments_count = excluded.comments_count,
                            is_comments_disabled = excluded.is_comments_disabled,
                            hashtags_json = excluded.hashtags_json,
                            dimensions_width = excluded.dimensions_width,
                            dimensions_height = excluded.dimensions_height,
                            engagement_count = excluded.engagement_count,
                            caption_length = excluded.caption_length,
                            hashtag_count = excluded.hashtag_count,
                            published_age_hours_at_collect = excluded.published_age_hours_at_collect,
                            caption_first_line = excluded.caption_first_line,
                            has_cta = excluded.has_cta,
                            has_question = excluded.has_question,
                            has_emoji = excluded.has_emoji,
                            is_image = excluded.is_image,
                            is_carousel = excluded.is_carousel,
                            is_video = excluded.is_video
                    """,
                    "params": [
                        post.post_url,
                        post.run_id,
                        post.source_handle,
                        post.published_at,
                        post.caption,
                        post.post_type,
                        json.dumps(post.media_urls, ensure_ascii=False),
                        post.hook_signal,
                        post.batch_date,
                        post.raw_archive_key or "",
                        post.instagram_post_id,
                        post.short_code,
                        post.owner_id,
                        post.owner_username,
                        post.owner_full_name,
                        post.likes_count,
                        post.comments_count,
                        int(post.is_comments_disabled),
                        json.dumps(post.hashtags, ensure_ascii=False),
                        post.dimensions_width,
                        post.dimensions_height,
                        post.engagement_count,
                        post.caption_length,
                        post.hashtag_count,
                        post.published_age_hours_at_collect,
                        post.caption_first_line,
                        int(post.has_cta),
                        int(post.has_question),
                        int(post.has_emoji),
                        int(post.is_image),
                        int(post.is_carousel),
                        int(post.is_video),
                        utc_now_iso(),
                    ],
                }
            )
        self._execute_batch(batch)

    def get_posts_for_run(self, run_id: str) -> list[CollectedPost]:
        rows = self._execute_query(
            """
                SELECT
                    instagram_post_id,
                    short_code,
                    owner_id,
                    owner_username,
                    owner_full_name,
                    source_handle,
                    post_url,
                    published_at,
                    caption,
                    post_type,
                    media_urls_json,
                    hook_signal,
                    batch_date,
                    raw_archive_key,
                    run_id,
                    likes_count,
                    comments_count,
                    is_comments_disabled,
                    hashtags_json,
                    dimensions_width,
                    dimensions_height,
                    engagement_count,
                    caption_length,
                    hashtag_count,
                    published_age_hours_at_collect,
                    caption_first_line,
                    has_cta,
                    has_question,
                    has_emoji,
                    is_image,
                    is_carousel,
                    is_video
                FROM collected_posts
                WHERE run_id = ?
                ORDER BY COALESCE(published_at, '') DESC, post_url DESC
            """,
            [run_id],
        )
        return [row_to_collected_post(row) for row in rows]

    def sync_run_posts_from_raw_archive(self, run_id: str, raw_payload: dict[str, Any]) -> int:
        run_rows = self._execute_query(
            """
                SELECT run_date, raw_archive_key
                FROM runs
                WHERE run_id = ?
            """,
            [run_id],
        )
        if not run_rows:
            raise RuntimeError(f"Kunde inte hitta körning i D1 för run_id={run_id}.")

        run_row = run_rows[0]
        run_date = str(run_row.get("run_date") or "")
        raw_archive_key = str(run_row.get("raw_archive_key") or "") or None
        items = raw_payload.get("items") or []
        if not isinstance(items, list):
            raise RuntimeError("Raw-arkivet saknar en giltig items-lista.")

        collected_at = parse_iso_datetime(raw_payload.get("archived_at"))
        source_accounts = build_source_accounts_from_raw_items(items)
        posts = normalize_post_items(
            items,
            source_accounts,
            batch_date=run_date,
            raw_archive_key=raw_archive_key,
            run_id=run_id,
            collected_at=collected_at,
        )
        self.insert_collected_posts(posts)
        return len(posts)

    def insert_candidates(self, run_id: str, candidates: list[CandidatePost]) -> None:
        if not candidates:
            return
        batch = []
        for candidate in candidates:
            post_url = candidate.source_post.post_url
            batch.append(
                {
                    "sql": """
                        INSERT INTO candidates (
                            candidate_key, run_id, post_url, source_handle, faiv_fit, lead_potential,
                            hook_strength, visual_transferability, novelty, total_score, faiv_content_category,
                            service_area, why_it_works, originality_risk, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(candidate_key) DO UPDATE SET
                            faiv_fit = excluded.faiv_fit,
                            lead_potential = excluded.lead_potential,
                            hook_strength = excluded.hook_strength,
                            visual_transferability = excluded.visual_transferability,
                            novelty = excluded.novelty,
                            total_score = excluded.total_score,
                            faiv_content_category = excluded.faiv_content_category,
                            service_area = excluded.service_area,
                            why_it_works = excluded.why_it_works,
                            originality_risk = excluded.originality_risk
                    """,
                    "params": [
                        candidate_key(run_id, post_url),
                        run_id,
                        post_url,
                        candidate.source_post.source_handle,
                        candidate.faiv_fit,
                        candidate.lead_potential,
                        candidate.hook_strength,
                        candidate.visual_transferability,
                        candidate.novelty,
                        candidate.total_score,
                        candidate.faiv_content_category,
                        candidate.service_area,
                        candidate.why_it_works,
                        candidate.originality_risk,
                        utc_now_iso(),
                    ],
                }
            )
        self._execute_batch(batch)

    def get_top_candidates_for_run(self, run_id: str, limit: int = 5) -> list[CandidatePost]:
        rows = self._execute_query(
            """
                SELECT
                    c.faiv_fit,
                    c.lead_potential,
                    c.hook_strength,
                    c.visual_transferability,
                    c.novelty,
                    c.total_score,
                    c.faiv_content_category,
                    c.service_area,
                    c.why_it_works,
                    c.originality_risk,
                    p.instagram_post_id,
                    p.short_code,
                    p.owner_id,
                    p.owner_username,
                    p.owner_full_name,
                    p.source_handle,
                    p.post_url,
                    p.published_at,
                    p.caption,
                    p.post_type,
                    p.media_urls_json,
                    p.hook_signal,
                    p.batch_date,
                    p.raw_archive_key,
                    p.run_id,
                    p.likes_count,
                    p.comments_count,
                    p.is_comments_disabled,
                    p.hashtags_json,
                    p.dimensions_width,
                    p.dimensions_height,
                    p.engagement_count,
                    p.caption_length,
                    p.hashtag_count,
                    p.published_age_hours_at_collect,
                    p.caption_first_line,
                    p.has_cta,
                    p.has_question,
                    p.has_emoji,
                    p.is_image,
                    p.is_carousel,
                    p.is_video
                FROM candidates c
                JOIN collected_posts p ON p.post_url = c.post_url
                WHERE c.run_id = ?
                ORDER BY c.total_score DESC, p.post_url DESC
                LIMIT ?
            """,
            [run_id, limit],
        )
        candidates: list[CandidatePost] = []
        for row in rows:
            source_post = row_to_collected_post(row)
            candidates.append(
                CandidatePost(
                    source_post=source_post,
                    faiv_fit=int(row["faiv_fit"]),
                    lead_potential=int(row["lead_potential"]),
                    hook_strength=int(row["hook_strength"]),
                    visual_transferability=int(row["visual_transferability"]),
                    novelty=int(row["novelty"]),
                    total_score=int(row["total_score"]),
                    faiv_content_category=str(row["faiv_content_category"]),
                    service_area=str(row.get("service_area", "")),
                    why_it_works=str(row["why_it_works"]),
                    originality_risk=str(row["originality_risk"]),
                )
            )
        return candidates

    def insert_proposals(self, run_id: str, proposals: list[Proposal]) -> None:
        if not proposals:
            return
        batch = []
        for proposal in proposals:
            post_url = proposal.source_candidate.source_post.post_url
            batch.append(
                {
                    "sql": """
                        INSERT INTO proposals (
                            proposal_key, run_id, post_url, source_handle, hook, caption, cta,
                            format, image_brief, recommended_asset_folder, fallback_image_prompt,
                            why_selected, faiv_content_category, service_area, status, drive_folder_url,
                            approved, used, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?)
                        ON CONFLICT(proposal_key) DO UPDATE SET
                            hook = excluded.hook,
                            caption = excluded.caption,
                            cta = excluded.cta,
                            format = excluded.format,
                            image_brief = excluded.image_brief,
                            recommended_asset_folder = excluded.recommended_asset_folder,
                            fallback_image_prompt = excluded.fallback_image_prompt,
                            why_selected = excluded.why_selected,
                            faiv_content_category = excluded.faiv_content_category,
                            service_area = excluded.service_area,
                            status = excluded.status,
                            drive_folder_url = excluded.drive_folder_url
                    """,
                    "params": [
                        proposal_key(run_id, post_url),
                        run_id,
                        post_url,
                        proposal.source_candidate.source_post.source_handle,
                        proposal.hook,
                        proposal.caption,
                        proposal.cta,
                        proposal.format,
                        proposal.image_brief,
                        proposal.recommended_asset_folder,
                        proposal.fallback_image_prompt,
                        proposal.why_selected,
                        proposal.faiv_content_category,
                        proposal.service_area,
                        proposal.status,
                        proposal.drive_folder_url,
                        utc_now_iso(),
                    ],
                }
            )
        self._execute_batch(batch)

    def _ensure_collected_posts_columns(self) -> None:
        rows = self._execute_query("PRAGMA table_info(collected_posts)")
        existing = {str(row.get("name") or "") for row in rows}
        for column_name, column_def in COLLECTED_POSTS_COLUMN_DEFS.items():
            if column_name in existing:
                continue
            self._execute_query(f"ALTER TABLE collected_posts ADD COLUMN {column_name} {column_def}")

    def _ensure_candidates_columns(self) -> None:
        rows = self._execute_query("PRAGMA table_info(candidates)")
        existing = {str(row.get("name") or "") for row in rows}
        migrations = {
            "service_area": "TEXT NOT NULL DEFAULT ''",
        }
        for column_name, column_def in migrations.items():
            if column_name not in existing:
                self._execute_query(f"ALTER TABLE candidates ADD COLUMN {column_name} {column_def}")

    def _ensure_proposals_columns(self) -> None:
        rows = self._execute_query("PRAGMA table_info(proposals)")
        existing = {str(row.get("name") or "") for row in rows}
        migrations = {
            "faiv_content_category": "TEXT NOT NULL DEFAULT ''",
            "service_area": "TEXT NOT NULL DEFAULT ''",
            "status": "TEXT NOT NULL DEFAULT 'needs_edit'",
            "drive_folder_url": "TEXT NOT NULL DEFAULT ''",
        }
        for column_name, column_def in migrations.items():
            if column_name not in existing:
                self._execute_query(f"ALTER TABLE proposals ADD COLUMN {column_name} {column_def}")

    def _execute_batch(self, batch: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not batch:
            return []
        data = self._post({"batch": batch})
        result = data.get("result", [])
        self._ensure_statement_success(result)
        return result

    def _execute_query(self, sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
        data = self._post({"sql": sql, "params": params or []})
        result = data.get("result", [])
        self._ensure_statement_success(result)
        if not result:
            return []
        return result[0].get("results", [])

    def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        response = self.session.post(
            self.query_endpoint,
            headers={
                "Authorization": f"Bearer {self.api_token}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=120,
        )
        response.raise_for_status()
        data = response.json()
        if not data.get("success", False):
            raise RuntimeError(f"D1-anrop misslyckades: {json.dumps(data.get('errors', []), ensure_ascii=False)}")
        return data

    def _ensure_statement_success(self, statements: list[dict[str, Any]]) -> None:
        for statement in statements:
            if not statement.get("success", False):
                raise RuntimeError(f"D1-query misslyckades: {json.dumps(statement, ensure_ascii=False)}")

    @property
    def query_endpoint(self) -> str:
        return (
            f"https://api.cloudflare.com/client/v4/accounts/{self.account_id}"
            f"/d1/database/{self.database_id}/query"
        )


def build_d1_store(app_config: AppConfig) -> CloudflareD1Store | None:
    configured_values = [
        app_config.cloudflare_account_id,
        app_config.cloudflare_api_token,
        app_config.cloudflare_d1_database_id,
    ]
    if not any(configured_values):
        return None

    missing = []
    if not app_config.cloudflare_account_id:
        missing.append("CLOUDFLARE_ACCOUNT_ID")
    if not app_config.cloudflare_api_token:
        missing.append("CLOUDFLARE_API_TOKEN")
    if not app_config.cloudflare_d1_database_id:
        missing.append("CLOUDFLARE_D1_DATABASE_ID")
    if missing:
        raise ConfigError(
            "Cloudflare D1-konfigurationen är ofullständig. Lägg in följande i .env/GitHub Secrets: "
            + ", ".join(missing)
            + "."
        )

    return CloudflareD1Store(
        account_id=app_config.cloudflare_account_id,
        api_token=app_config.cloudflare_api_token,
        database_id=app_config.cloudflare_d1_database_id,
    )


def row_to_collected_post(row: dict[str, Any]) -> CollectedPost:
    return CollectedPost(
        source_handle=str(row.get("source_handle") or ""),
        post_url=str(row.get("post_url") or ""),
        published_at=str(row.get("published_at") or ""),
        caption=str(row.get("caption") or ""),
        post_type=str(row.get("post_type") or ""),
        media_urls=json.loads(row.get("media_urls_json") or "[]"),
        hook_signal=str(row.get("hook_signal") or ""),
        batch_date=str(row.get("batch_date") or ""),
        raw_archive_key=str(row.get("raw_archive_key") or "") or None,
        raw_payload={},
        run_id=str(row.get("run_id") or ""),
        instagram_post_id=str(row.get("instagram_post_id") or ""),
        short_code=str(row.get("short_code") or ""),
        owner_id=str(row.get("owner_id") or ""),
        owner_username=str(row.get("owner_username") or ""),
        owner_full_name=str(row.get("owner_full_name") or ""),
        likes_count=to_int(row.get("likes_count")),
        comments_count=to_int(row.get("comments_count")),
        is_comments_disabled=to_bool(row.get("is_comments_disabled")),
        hashtags=parse_json_list(row.get("hashtags_json")),
        dimensions_width=to_optional_int(row.get("dimensions_width")),
        dimensions_height=to_optional_int(row.get("dimensions_height")),
        engagement_count=to_int(row.get("engagement_count")),
        caption_length=to_int(row.get("caption_length")),
        hashtag_count=to_int(row.get("hashtag_count")),
        published_age_hours_at_collect=to_optional_int(row.get("published_age_hours_at_collect")),
        caption_first_line=str(row.get("caption_first_line") or ""),
        has_cta=to_bool(row.get("has_cta")),
        has_question=to_bool(row.get("has_question")),
        has_emoji=to_bool(row.get("has_emoji")),
        is_image=to_bool(row.get("is_image")),
        is_carousel=to_bool(row.get("is_carousel")),
        is_video=to_bool(row.get("is_video")),
    )


def candidate_key(run_id: str, post_url: str) -> str:
    return f"{run_id}|{post_url}"


def proposal_key(run_id: str, post_url: str) -> str:
    return f"{run_id}|{post_url}"


def split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_json_list(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if str(item).strip()]


def to_int(value: Any) -> int:
    try:
        if value is None or value == "":
            return 0
        return int(value)
    except (TypeError, ValueError):
        return 0


def to_optional_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value in (1, "1", "true", "True", "yes", "YES"):
        return True
    return False


def parse_iso_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def build_source_accounts_from_raw_items(items: Iterable[dict[str, Any]]) -> list[SourceAccount]:
    sources: list[SourceAccount] = []
    seen: set[str] = set()
    for item in items:
        handle = str(item.get("ownerUsername") or "").strip()
        if not handle:
            continue
        key = handle.casefold()
        if key in seen:
            continue
        seen.add(key)
        company_name = str(item.get("ownerFullName") or handle).strip() or handle
        sources.append(
            SourceAccount(
                priority=999,
                tier="raw",
                company_name=company_name,
                raw_lookup=f"@{handle}",
                lookup_term=handle,
                country="",
                faiv_categories=[],
                frequency="",
                comment="",
                handle=handle,
                active=True,
            )
        )
    return sources
