from __future__ import annotations

from pathlib import Path
import hashlib

from src.analyze import OpenRouterClient, analyze_posts
from src.assets import build_asset_library_rows_from_drive, match_asset_folder
from src.collect import ApifyCollector
from src.config import AppConfig, RuntimeSettings, today_stockholm
from src.deliver import DeliveryService
from src.d1 import build_d1_store
from src.models import Proposal, RunSummary
from src.raw_archive import build_raw_archive_client
from src.sheets import GoogleWorkspaceClient
from src.watchlist import assign_batches, next_batch, parse_watchlist_markdown, source_account_to_row
from src.propose import generate_proposals


def bootstrap_workspace(
    workspace_client: GoogleWorkspaceClient,
    spreadsheet_id: str,
    watchlist_path: Path,
) -> None:
    workspace_client.ensure_tabs(spreadsheet_id)
    _sync_sources(workspace_client, spreadsheet_id, watchlist_path)


def sync_asset_library(
    workspace_client: GoogleWorkspaceClient,
    spreadsheet_id: str,
    asset_root_folder_id: str,
) -> int:
    files = workspace_client.list_asset_files(asset_root_folder_id)
    rows = build_asset_library_rows_from_drive(files)
    workspace_client.replace_tab(spreadsheet_id, "Asset Library", rows)
    return len(rows)


def run_pipeline(
    *,
    app_config: AppConfig,
    workspace_client: GoogleWorkspaceClient,
    watchlist_path: Path,
) -> RunSummary:
    if not app_config.spreadsheet_id:
        raise RuntimeError("GOOGLE_SPREADSHEET_ID saknas. Kör bootstrap-kommandot först och spara spreadsheet-id som secret/variabel.")

    workspace_client.ensure_tabs(app_config.spreadsheet_id)
    _sync_sources(workspace_client, app_config.spreadsheet_id, watchlist_path)

    settings_map = workspace_client.read_settings(app_config.spreadsheet_id)
    runtime = RuntimeSettings.from_sheet(settings_map, app_config)
    run_date = today_stockholm().date().isoformat()
    run_id = build_run_id(run_date, runtime.active_batch)
    d1_store = build_d1_store(app_config)
    if d1_store is not None:
        d1_store.ensure_schema()

    source_rows = workspace_client.read_tab(app_config.spreadsheet_id, "Sources")
    active_sources = [row for row in source_rows if row.get("active", "").lower() == "yes" and row.get("batch") == runtime.active_batch]
    accounts = [
        _row_to_source_account(row)
        for row in active_sources
    ]

    if d1_store is not None:
        d1_store.upsert_sources(source_rows)
        existing_urls = d1_store.get_existing_post_urls([account.handle or account.lookup_term for account in accounts])
    else:
        existing_urls = {row["post_url"] for row in workspace_client.read_tab(app_config.spreadsheet_id, "Collected Posts") if row.get("post_url")}
    if d1_store is not None:
        latest_dates = d1_store.get_latest_post_dates([account.handle or account.lookup_term for account in accounts])
    else:
        latest_dates = {}

    collector = ApifyCollector(
        app_config.apify_token,
        runtime.apify_actor_id,
        raw_archive=build_raw_archive_client(app_config),
    )
    collection = collector.collect_posts_for_sources(
        accounts,
        posts_per_account=runtime.posts_per_account,
        batch_date=run_date,
        existing_urls=existing_urls,
        only_posts_newer_than=latest_dates,
    )
    for post in collection.posts:
        post.run_id = run_id
    workspace_client.replace_tab(
        app_config.spreadsheet_id,
        "Sources",
        merge_updated_source_rows(source_rows, collection.updated_sources),
    )
    merged_source_rows = merge_updated_source_rows(source_rows, collection.updated_sources)
    if d1_store is not None:
        d1_store.upsert_sources(merged_source_rows)
        d1_store.record_run_start(
            run_id=run_id,
            run_date=run_date,
            active_batch=runtime.active_batch,
            source_count=len(accounts),
            raw_archive_key=collection.raw_archive_key,
        )
        d1_store.insert_collected_posts(collection.posts)

    posts_for_analysis = d1_store.get_posts_for_run(run_id) if d1_store is not None else collection.posts

    workspace_client.append_rows(
        app_config.spreadsheet_id,
        "Collected Posts",
        [
            {
                "run_id": post.run_id,
                "source_handle": post.source_handle,
                "post_url": post.post_url,
                "published_at": post.published_at,
                "caption": post.caption,
                "post_type": post.post_type,
                "media_urls": post.media_urls,
                "hook_signal": post.hook_signal,
                "batch_date": post.batch_date,
                "raw_archive_key": post.raw_archive_key or "",
            }
            for post in collection.posts
        ],
    )

    client = OpenRouterClient(app_config.openrouter_api_key)
    candidates = analyze_posts(
        posts_for_analysis,
        min_score=runtime.min_score,
        model=runtime.analysis_model,
        client=client,
    )
    if d1_store is not None:
        d1_store.insert_candidates(run_id, candidates)
    workspace_client.append_rows(
        app_config.spreadsheet_id,
        "Candidates",
        [
            {
                "run_id": run_id,
                "source_handle": candidate.source_post.source_handle,
                "post_url": candidate.source_post.post_url,
                "faiv_fit": candidate.faiv_fit,
                "lead_potential": candidate.lead_potential,
                "hook_strength": candidate.hook_strength,
                "visual_transferability": candidate.visual_transferability,
                "novelty": candidate.novelty,
                "total_score": candidate.total_score,
                "faiv_category": candidate.faiv_category,
                "why_it_works": candidate.why_it_works,
                "originality_risk": candidate.originality_risk,
                "batch_date": candidate.source_post.batch_date,
            }
            for candidate in candidates
        ],
    )

    top_candidates = d1_store.get_top_candidates_for_run(run_id, limit=5) if d1_store is not None else candidates[:5]
    proposals: list[Proposal] = generate_proposals(
        top_candidates,
        model=runtime.proposal_model,
        fallback_model=runtime.fallback_model,
        client=client,
    )

    asset_rows = workspace_client.read_tab(app_config.spreadsheet_id, "Asset Library")
    final_proposals: list[Proposal] = []
    for proposal in proposals:
        match = match_asset_folder(proposal, asset_rows)
        proposal.recommended_asset_folder = match.folder
        if match.use_ai_prompt and "AI-prompt krävs:" not in proposal.fallback_image_prompt:
            proposal.fallback_image_prompt = f"AI-prompt krävs: {proposal.fallback_image_prompt}"
        final_proposals.append(proposal)
    if d1_store is not None:
        d1_store.insert_proposals(run_id, final_proposals)

    workspace_client.append_rows(
        app_config.spreadsheet_id,
        "Approved Proposals",
        [
            {
                "run_id": run_id,
                "source_handle": proposal.source_candidate.source_post.source_handle,
                "post_url": proposal.source_candidate.source_post.post_url,
                "hook": proposal.hook,
                "caption": proposal.caption,
                "cta": proposal.cta,
                "format": proposal.format,
                "image_brief": proposal.image_brief,
                "recommended_asset_folder": proposal.recommended_asset_folder,
                "fallback_image_prompt": proposal.fallback_image_prompt,
                "why_selected": proposal.why_selected,
                "approved": "",
                "used": "",
                "run_date": run_date,
            }
            for proposal in final_proposals
        ],
    )

    summary = RunSummary(
        run_id=run_id,
        run_date=run_date,
        active_batch=runtime.active_batch,
        source_count=len(accounts),
        collected_count=len(collection.posts),
        candidate_count=len(candidates),
        proposal_count=len(final_proposals),
        blocked_accounts=collection.blocked_accounts,
        warnings=list(collection.warnings),
        errors=[],
        raw_archive_key=collection.raw_archive_key,
    )

    delivery = DeliveryService(workspace_client, app_config)
    try:
        summary.doc_url = delivery.create_daily_document(final_proposals, summary)
    except Exception as error:  # noqa: BLE001
        summary.errors.append(f"Kunde inte skapa Google Doc: {error}")

    summary.status = "completed_with_errors" if summary.errors else "completed"

    workspace_client.append_rows(
        app_config.spreadsheet_id,
        "Run Log",
        [
            {
                "run_id": summary.run_id,
                "run_date": summary.run_date,
                "active_batch": summary.active_batch,
                "source_count": summary.source_count,
                "collected_count": summary.collected_count,
                "candidate_count": summary.candidate_count,
                "proposal_count": summary.proposal_count,
                "blocked_accounts": ", ".join(summary.blocked_accounts),
                "warnings": " | ".join(summary.warnings),
                "errors": " | ".join(summary.errors),
                "doc_url": summary.doc_url or "",
                "raw_archive_key": collection.raw_archive_key or "",
                "status": summary.status,
            }
        ],
    )
    if d1_store is not None:
        d1_store.update_run_summary(summary)
    workspace_client.upsert_settings(
        app_config.spreadsheet_id,
        {"active_batch": next_batch(runtime.active_batch)},
    )

    return summary


def _sync_sources(workspace_client: GoogleWorkspaceClient, spreadsheet_id: str, watchlist_path: Path) -> None:
    watchlist = watchlist_path.read_text(encoding="utf-8")
    parsed = assign_batches(parse_watchlist_markdown(watchlist))
    existing_rows = workspace_client.read_tab(spreadsheet_id, "Sources")
    existing_map = {
        row.get("handle") or row.get("lookup_term"): row
        for row in existing_rows
        if row.get("handle") or row.get("lookup_term")
    }
    merged_rows = []
    for account in parsed:
        row = source_account_to_row(account)
        existing = existing_map.get(account.handle or account.lookup_term, {})
        if existing:
            row["active"] = existing.get("active", row["active"])
            row["last_fetched"] = existing.get("last_fetched", row["last_fetched"])
            row["status"] = existing.get("status", row["status"])
        merged_rows.append(row)
    workspace_client.replace_tab(spreadsheet_id, "Sources", merged_rows)


def _row_to_source_account(row: dict[str, str]):
    return _source_account_from_row(row)


def _source_account_from_row(row: dict[str, str]):
    from src.models import SourceAccount

    return SourceAccount(
        priority=int(row.get("priority", "999") or 999),
        tier=row.get("tier", ""),
        company_name=row.get("company_name", ""),
        raw_lookup=row.get("lookup_term", ""),
        lookup_term=row.get("lookup_term", ""),
        country=row.get("country", ""),
        faiv_categories=[item.strip() for item in row.get("category_fit", "").split(",") if item.strip()],
        frequency=row.get("frequency", ""),
        comment=row.get("comment", ""),
        handle=row.get("handle") or None,
        active=row.get("active", "").lower() == "yes",
        batch=row.get("batch", ""),
        last_fetched=row.get("last_fetched", ""),
        status=row.get("status", "ok"),
    )


def merge_updated_source_rows(source_rows: list[dict[str, str]], updated_sources: list) -> list[dict[str, str]]:
    updated_map = {
        source.handle or source.lookup_term: source
        for source in updated_sources
    }
    merged_rows: list[dict[str, str]] = []
    for row in source_rows:
        key = row.get("handle") or row.get("lookup_term")
        updated = updated_map.get(key)
        merged = dict(row)
        if updated:
            merged["status"] = updated.status
            merged["last_fetched"] = updated.last_fetched
            merged["active"] = "yes" if updated.active else "no"
        merged_rows.append(merged)
    return merged_rows


def build_run_id(run_date: str, active_batch: str) -> str:
    timestamp = today_stockholm().strftime("%H%M%S")
    digest = hashlib.sha1(f"{run_date}|{active_batch}|{timestamp}".encode("utf-8")).hexdigest()[:8]
    return f"{run_date}-{active_batch}-{timestamp}-{digest}"
