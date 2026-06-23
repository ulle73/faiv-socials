from __future__ import annotations

import json
from typing import Any

from src.config import AppConfig, PROPOSAL_STATUSES
from src.models import Proposal, RunSummary
from src.sheets import GoogleWorkspaceClient


def should_create_document(proposal_count: int) -> bool:
    return proposal_count >= 1


class DeliveryService:
    def __init__(self, workspace_client: GoogleWorkspaceClient, app_config: AppConfig) -> None:
        self.workspace_client = workspace_client
        self.app_config = app_config

    def create_daily_document(self, proposals: list[Proposal], summary: RunSummary) -> str | None:
        if not should_create_document(len(proposals)):
            return None

        title = f"FAIV - Dagens postpaket - {summary.run_date}"
        document = self.workspace_client.docs_service.documents().create(body={"title": title}).execute()
        document_id = document["documentId"]
        if self.app_config.output_folder_id:
            self.workspace_client.move_file_to_folder(document_id, self.app_config.output_folder_id)

        content = _render_document_body(proposals, summary)
        self.workspace_client.docs_service.documents().batchUpdate(
            documentId=document_id,
            body={"requests": [{"insertText": {"location": {"index": 1}, "text": content}}]},
        ).execute()
        return f"https://docs.google.com/document/d/{document_id}/edit"

    def create_post_packages(self, proposals: list[Proposal], run_date: str) -> list[str]:
        if not self.app_config.output_folder_id:
            return []

        date_folder = self._ensure_folder(str(run_date), self.app_config.output_folder_id)
        urls: list[str] = []

        for index, proposal in enumerate(proposals, start=1):
            folder_name = f"{index:02d}_{_slugify(proposal.faiv_content_category)}_{_slugify(proposal.service_area)}"
            pkg_folder = self._ensure_folder(folder_name, date_folder)
            folder_url = f"https://drive.google.com/drive/folders/{pkg_folder}"
            proposal.drive_folder_url = folder_url

            self._write_file(pkg_folder, "post.md", _render_post_md(proposal))
            self._write_file(pkg_folder, "caption.txt", proposal.caption)
            self._write_file(pkg_folder, "source.json", _render_source_json(proposal))
            self._write_file(pkg_folder, "proposal.json", json.dumps(
                _proposal_to_dict(proposal), ensure_ascii=False, indent=2
            ))
            self._write_file(pkg_folder, "asset_plan.json", json.dumps(
                _asset_plan_to_dict(proposal), ensure_ascii=False, indent=2
            ))

            if proposal.status == "needs_ai_image":
                self._write_file(pkg_folder, "image_prompt.txt", proposal.fallback_image_prompt)
            elif proposal.status == "needs_photo":
                self._write_file(pkg_folder, "shotlist.txt", proposal.image_plan or proposal.image_brief)

            if proposal.carousel_structure:
                self._write_file(pkg_folder, "slide_texts.txt", _render_slide_texts(proposal))

            urls.append(folder_url)

        return urls

    def _ensure_folder(self, name: str, parent_id: str) -> str:
        existing = self.workspace_client.drive_service.files().list(
            q=f"name = '{name}' and '{parent_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false",
            fields="files(id)",
            pageSize=1,
        ).execute()
        files = existing.get("files", [])
        if files:
            return files[0]["id"]
        folder = self.workspace_client.drive_service.files().create(
            body={"name": name, "mimeType": "application/vnd.google-apps.folder", "parents": [parent_id]},
            fields="id",
        ).execute()
        return folder["id"]

    def _write_file(self, folder_id: str, file_name: str, content: str) -> None:
        import io
        from googleapiclient.http import MediaIoBaseUpload

        media = MediaIoBaseUpload(io.BytesIO(content.encode("utf-8")), mimetype="text/plain", resumable=False)
        self.workspace_client.drive_service.files().create(
            body={"name": file_name, "parents": [folder_id]},
            media_body=media,
            fields="id",
        ).execute()


def _slugify(text: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in text.lower().strip())[:40] or "okant"


def _proposal_to_dict(proposal: Proposal) -> dict:
    return {
        "hook": proposal.hook,
        "caption": proposal.caption,
        "cta": proposal.cta,
        "format": proposal.format,
        "image_brief": proposal.image_brief,
        "recommended_asset_folder": proposal.recommended_asset_folder,
        "fallback_image_prompt": proposal.fallback_image_prompt,
        "why_selected": proposal.why_selected,
        "faiv_content_category": proposal.faiv_content_category,
        "service_area": proposal.service_area,
        "status": proposal.status,
        "overlay_text": proposal.overlay_text,
        "carousel_structure": proposal.carousel_structure,
        "image_plan": proposal.image_plan,
        "asset_match_confidence": proposal.asset_match_confidence,
        "selected_asset": proposal.selected_asset,
        "production_note": proposal.production_note,
        "originality_risk": proposal.originality_risk,
        "drive_folder_url": proposal.drive_folder_url,
        "dedupe_key": proposal.dedupe_key,
    }


def _asset_plan_to_dict(proposal: Proposal) -> dict:
    return {
        "selected_asset": proposal.selected_asset,
        "asset_match_confidence": proposal.asset_match_confidence,
        "asset_reasoning": proposal.recommended_asset_folder,
        "final_image_exists": proposal.status == "ready_to_post",
        "ai_image_needed": proposal.status == "needs_ai_image",
        "photo_needed": proposal.status == "needs_photo",
    }


def _render_source_json(proposal: Proposal) -> str:
    post = proposal.source_candidate.source_post
    return json.dumps({
        "original_post_url": post.post_url,
        "source_account": post.source_handle,
        "collected_at": post.batch_date,
        "original_caption": post.caption,
        "original_media_urls": post.media_urls,
        "apify_run_id": post.run_id,
        "dedupe_key": proposal.dedupe_key,
    }, ensure_ascii=False, indent=2)


def _render_slide_texts(proposal: Proposal) -> str:
    lines: list[str] = []
    for i, slide in enumerate(proposal.carousel_structure, start=1):
        lines.append(f"Slide {i}:")
        lines.append(f"  Purpose: {slide.get('purpose', '')}")
        lines.append(f"  Overlay: {slide.get('overlay_text', '')}")
        lines.append(f"  Image need: {slide.get('image_need', '')}")
        if slide.get("image_prompt_if_needed"):
            lines.append(f"  Image prompt: {slide['image_prompt_if_needed']}")
        lines.append("")
    return "\n".join(lines)


def _render_post_md(proposal: Proposal) -> str:
    lines = [
        f"# FAIV-postpaket",
        f"",
        f"**Status:** {proposal.status}",
        f"**FAIV-kategori:** {proposal.faiv_content_category}",
        f"**Tjanteomrade:** {proposal.service_area}",
        f"**Format:** {proposal.format}",
        f"",
        f"## Originalkalla",
        f"- Konto: {proposal.source_candidate.source_post.source_handle}",
        f"- URL: {proposal.source_candidate.source_post.post_url}",
        f"",
        f"## Varfor originalet fungerar",
        f"{proposal.source_candidate.why_it_works}",
        f"",
        f"## FAIV-vinkel",
        f"{proposal.why_selected}",
        f"",
        f"## Hook",
        f"{proposal.hook}",
        f"",
        f"## Caption",
        f"{proposal.caption}",
        f"",
        f"## CTA",
        f"{proposal.cta}",
        f"",
    ]
    if proposal.overlay_text:
        lines.append(f"## Overlay-text")
        lines.append(proposal.overlay_text)
        lines.append("")

    if proposal.carousel_structure:
        lines.append("## Slide-struktur")
        for i, slide in enumerate(proposal.carousel_structure, start=1):
            lines.append(f"### Slide {i}")
            lines.append(f"- Syfte: {slide.get('purpose', '')}")
            lines.append(f"- Overlay: {slide.get('overlay_text', '')}")
            lines.append(f"- Bildbehov: {slide.get('image_need', '')}")
            lines.append("")
    else:
        lines.append("## Bildplan")
        lines.append(proposal.image_plan or proposal.image_brief)
        lines.append("")

    if proposal.selected_asset:
        lines.append(f"## Vald FAIV-bild")
        lines.append(f"- Asset: {proposal.selected_asset}")
        lines.append(f"- Match confidence: {proposal.asset_match_confidence}")
        lines.append("")

    if proposal.fallback_image_prompt:
        lines.append("## AI-bildprompt")
        lines.append(proposal.fallback_image_prompt)
        lines.append("")

    lines.append(f"## Originalitetsrisk")
    lines.append(proposal.originality_risk or "okand")
    lines.append("")
    lines.append(f"## Produktionsnotering")
    lines.append(proposal.production_note or "Ingen notering.")
    lines.append("")

    return "\n".join(lines)


def _render_document_body(proposals: list[Proposal], summary: RunSummary) -> str:
    lines: list[str] = [
        f"FAIV - Dagens postpaket ({summary.run_date})",
        f"",
        f"Batch: {summary.active_batch}",
        f"Hamtade poster: {summary.collected_count}",
        f"Kandidater: {summary.candidate_count}",
        f"Postpaket: {summary.proposal_count}",
        f"",
    ]

    status_sections: dict[str, list[Proposal]] = {s: [] for s in PROPOSAL_STATUSES}
    for p in proposals:
        status_sections.setdefault(p.status, []).append(p)

    section_titles = {
        "ready_to_post": "Klara att publicera",
        "ready_to_design": "Klara for design",
        "needs_photo": "Behover foto",
        "needs_ai_image": "Behover AI-bild",
        "needs_edit": "Behover redigering",
        "discarded": "Ej valda / svaga kandidater",
    }

    for status in PROPOSAL_STATUSES:
        items = status_sections.get(status, [])
        if not items:
            continue
        title = section_titles.get(status, status)
        lines.append(f"## {title}")
        lines.append("")
        for i, p in enumerate(items, start=1):
            lines.append(f"{i}. {p.faiv_content_category} - {p.service_area}")
            lines.append(f"   Status: {p.status}")
            lines.append(f"   Format: {p.format}")
            lines.append(f"   Hook: {p.hook}")
            if p.drive_folder_url:
                lines.append(f"   Drive-mapp: {p.drive_folder_url}")
            lines.append("")

    if summary.warnings:
        lines.append("## Varningar")
        for w in summary.warnings:
            lines.append(f"- {w}")
        lines.append("")

    if summary.errors:
        lines.append("## Fel")
        for e in summary.errors:
            lines.append(f"- {e}")
        lines.append("")

    lines.append("## Driftstatus")
    lines.append(f"Status: {summary.status}")
    if summary.raw_archive_key:
        lines.append(f"Raw archive: {summary.raw_archive_key}")
    lines.append("")

    return "\n".join(lines)
