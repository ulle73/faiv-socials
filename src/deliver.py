from __future__ import annotations

import smtplib
from email.message import EmailMessage

from src.config import AppConfig, ConfigError
from src.models import Proposal, RunSummary
from src.sheets import GoogleWorkspaceClient


def should_create_document(proposal_count: int) -> bool:
    return proposal_count >= 3


def build_status_email(summary: RunSummary) -> tuple[str, str]:
    subject = f"FAIV sociala medier — körning {summary.run_date} batch {summary.active_batch}"
    lines = [
        f"Kördatum: {summary.run_date}",
        f"Aktiv batch: {summary.active_batch}",
        f"Hämtade poster: {summary.collected_count}",
        f"Kandidater: {summary.candidate_count}",
        f"Färdiga förslag: {summary.proposal_count}",
    ]
    if summary.doc_url:
        lines.append(f"Dagens doc: {summary.doc_url}")
    if summary.blocked_accounts:
        lines.append(f"Blockerade konton: {', '.join(summary.blocked_accounts)}")
    if summary.warnings:
        lines.append("Varningar:")
        lines.extend(f"- {warning}" for warning in summary.warnings)
    if summary.errors:
        lines.append("Fel:")
        lines.extend(f"- {error}" for error in summary.errors)
    return subject, "\n".join(lines)


class DeliveryService:
    def __init__(self, workspace_client: GoogleWorkspaceClient, app_config: AppConfig) -> None:
        self.workspace_client = workspace_client
        self.app_config = app_config

    def create_daily_document(self, proposals: list[Proposal], summary: RunSummary, notify_email: str) -> str | None:
        if not should_create_document(len(proposals)):
            return None

        title = f"FAIV – Dagens 5 bästa inspirationer – {summary.run_date}"
        document = self.workspace_client.docs_service.documents().create(body={"title": title}).execute()
        document_id = document["documentId"]
        if self.app_config.output_folder_id:
            self.workspace_client.move_file_to_folder(document_id, self.app_config.output_folder_id)
        self.workspace_client.share_file(document_id, notify_email, role="writer")

        content = _render_document_body(proposals, summary)
        self.workspace_client.docs_service.documents().batchUpdate(
            documentId=document_id,
            body={"requests": [{"insertText": {"location": {"index": 1}, "text": content}}]},
        ).execute()
        return f"https://docs.google.com/document/d/{document_id}/edit"

    def send_status_email(self, notify_email: str, summary: RunSummary) -> None:
        if not self.app_config.smtp_host or not self.app_config.smtp_username or not self.app_config.smtp_password or not self.app_config.smtp_from:
            raise ConfigError(
                "SMTP saknas. Sätt SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD och SMTP_FROM för e-postleverans."
            )
        subject, body = build_status_email(summary)
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = self.app_config.smtp_from
        message["To"] = notify_email
        message.set_content(body)

        with smtplib.SMTP(self.app_config.smtp_host, self.app_config.smtp_port, timeout=30) as server:
            server.starttls()
            server.login(self.app_config.smtp_username, self.app_config.smtp_password)
            server.send_message(message)


def _render_document_body(proposals: list[Proposal], summary: RunSummary) -> str:
    lines = [
        f"FAIV – Dagens bästa sociala medier-idéer ({summary.run_date})",
        "",
        f"Batch: {summary.active_batch}",
        f"Hämtade poster: {summary.collected_count}",
        f"Kandidater: {summary.candidate_count}",
        "",
    ]
    for index, proposal in enumerate(proposals, start=1):
        candidate = proposal.source_candidate
        lines.extend(
            [
                f"{index}. {candidate.source_post.source_handle}",
                f"Originalpost: {candidate.source_post.post_url}",
                f"Varför den fungerar: {candidate.why_it_works}",
                f"FAIV-kategori: {candidate.faiv_category}",
                f"Hook: {proposal.hook}",
                f"Caption: {proposal.caption}",
                f"CTA: {proposal.cta}",
                f"Format: {proposal.format}",
                f"Bildbrief: {proposal.image_brief}",
                f"Bildmapp: {proposal.recommended_asset_folder}",
                f"Fallback-prompt: {proposal.fallback_image_prompt}",
                "",
            ]
        )
    return "\n".join(lines)
