from __future__ import annotations

from pathlib import Path
from typing import Iterable

from src.collect import ApifyCollector
from src.config import AppConfig, ConfigError, today_stockholm
from src.d1 import build_d1_store
from src.models import RunSummary, SourceAccount
from src.pipeline import build_run_id
from src.raw_archive import build_raw_archive_client
from src.watchlist import assign_batches, parse_watchlist_markdown, source_account_to_row


def run_collection_only(
    *,
    app_config: AppConfig,
    watchlist_path: Path,
    batch: str = "A",
    posts_per_account: int = 1,
    handles: list[str] | None = None,
    throttle_seconds: float = 2.0,
) -> RunSummary:
    d1_store = build_d1_store(app_config)
    if d1_store is None:
        raise ConfigError("Cloudflare D1 saknas. Sätt CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_API_TOKEN och CLOUDFLARE_D1_DATABASE_ID.")

    raw_archive = build_raw_archive_client(app_config)
    if raw_archive is None:
        raise ConfigError("R2 saknas. Sätt R2_BUCKET, R2_ENDPOINT/R2_ACCOUNT_ID och R2-nycklarna.")

    parsed_accounts = assign_batches(parse_watchlist_markdown(watchlist_path.read_text(encoding="utf-8")))
    selected_accounts = select_accounts_for_collection(parsed_accounts, batch=batch, handles=handles)

    run_date = today_stockholm().date().isoformat()
    active_batch = "CUSTOM" if handles else batch.upper()
    run_id = build_run_id(run_date, active_batch)

    d1_store.ensure_schema()
    d1_store.upsert_sources([source_account_to_row(account) for account in parsed_accounts])

    existing_urls = d1_store.get_existing_post_urls([account.handle or account.lookup_term for account in selected_accounts])
    latest_dates = d1_store.get_latest_post_dates([account.handle or account.lookup_term for account in selected_accounts])

    collector = ApifyCollector(
        app_config.apify_token,
        "apify/instagram-post-scraper",
        raw_archive=raw_archive,
    )
    collection = collector.collect_posts_for_sources(
        selected_accounts,
        posts_per_account=posts_per_account,
        batch_date=run_date,
        existing_urls=existing_urls,
        throttle_seconds=throttle_seconds,
        only_posts_newer_than=latest_dates,
    )
    for post in collection.posts:
        post.run_id = run_id

    d1_store.upsert_sources([source_account_to_row(account) for account in parsed_accounts])
    d1_store.record_run_start(
        run_id=run_id,
        run_date=run_date,
        active_batch=active_batch,
        source_count=len(selected_accounts),
        raw_archive_key=collection.raw_archive_key,
    )
    d1_store.insert_collected_posts(collection.posts)

    summary = RunSummary(
        run_id=run_id,
        run_date=run_date,
        active_batch=active_batch,
        source_count=len(selected_accounts),
        collected_count=len(collection.posts),
        candidate_count=0,
        proposal_count=0,
        blocked_accounts=collection.blocked_accounts,
        warnings=list(collection.warnings),
        errors=[],
        raw_archive_key=collection.raw_archive_key,
        status="collected_with_warnings" if collection.warnings else "collected",
    )
    d1_store.update_run_summary(summary)
    return summary


def select_accounts_for_collection(
    accounts: Iterable[SourceAccount],
    *,
    batch: str,
    handles: list[str] | None,
) -> list[SourceAccount]:
    account_list = list(accounts)
    if handles:
        wanted = {normalize_handle(handle) for handle in handles}
        matched_accounts = [
            account
            for account in account_list
            if account.active and normalize_handle(account.handle or account.lookup_term) in wanted
        ]
        matched_keys = {normalize_handle(account.handle or account.lookup_term) for account in matched_accounts}
        missing_handles = [handle for handle in handles if normalize_handle(handle) not in matched_keys]
        synthetic_accounts = [build_synthetic_source_account(handle) for handle in missing_handles]
        return matched_accounts + synthetic_accounts

    selected_batch = (batch or "A").upper()
    return [
        account
        for account in account_list
        if account.active and account.batch.upper() == selected_batch
    ]


def normalize_handle(value: str) -> str:
    normalized = (value or "").strip().lstrip("@").strip("/")
    if normalized.startswith("https://") or normalized.startswith("http://"):
        normalized = normalized.rstrip("/").split("/")[-1]
    return normalized.casefold()


def build_synthetic_source_account(handle: str) -> SourceAccount:
    normalized = normalize_handle(handle)
    display_handle = normalized
    return SourceAccount(
        priority=999,
        tier="manual",
        company_name=display_handle,
        raw_lookup=f"@{display_handle}",
        lookup_term=f"@{display_handle}",
        country="",
        faiv_categories=[],
        frequency="Manuell",
        comment="Skapad från explicit handle",
        handle=display_handle,
        active=True,
        batch="",
        status="ok",
    )
