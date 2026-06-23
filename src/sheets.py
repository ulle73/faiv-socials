from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from src.config import DEFAULT_SETTINGS


SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents",
]

TAB_HEADERS = {
    "Settings": ["key", "value"],
    "Sources": [
        "handle",
        "lookup_term",
        "company_name",
        "priority",
        "tier",
        "country",
        "category_fit",
        "frequency",
        "active",
        "batch",
        "last_fetched",
        "status",
        "comment",
    ],
    "Collected Posts": [
        "run_id",
        "source_handle",
        "post_url",
        "published_at",
        "caption",
        "post_type",
        "media_urls",
        "hook_signal",
        "batch_date",
        "raw_archive_key",
    ],
    "Candidates": [
        "run_id",
        "source_handle",
        "post_url",
        "faiv_fit",
        "lead_potential",
        "hook_strength",
        "visual_transferability",
        "novelty",
        "total_score",
        "faiv_content_category",
        "service_area",
        "why_it_works",
        "originality_risk",
        "batch_date",
    ],
    "Approved Proposals": [
        "run_id",
        "source_handle",
        "post_url",
        "hook",
        "caption",
        "cta",
        "format",
        "image_brief",
        "recommended_asset_folder",
        "fallback_image_prompt",
        "why_selected",
        "approved",
        "used",
        "run_date",
        "faiv_content_category",
        "service_area",
        "status",
        "drive_folder_url",
    ],
    "Asset Library": ["folder", "file_name", "category", "keywords"],
    "Run Log": [
        "run_id",
        "run_date",
        "active_batch",
        "source_count",
        "collected_count",
        "candidate_count",
        "proposal_count",
        "blocked_accounts",
        "warnings",
        "errors",
        "doc_url",
        "raw_archive_key",
        "status",
    ],
}


def load_credentials(
    client_secrets_path: str | Path,
    token_path: str | Path | None = None,
) -> Credentials:
    """Load OAuth user credentials, running interactive flow if needed."""
    client_secrets_path = Path(client_secrets_path)
    if not client_secrets_path.exists():
        raise FileNotFoundError(
            f"OAuth client secrets file not found: {client_secrets_path}"
        )

    token_path = Path(token_path) if token_path else Path(".google_token.json")

    if token_path.exists():
        token_data = token_path.read_text(encoding="utf-8-sig")
        creds = Credentials.from_authorized_user_info(json.loads(token_data), SCOPES)
    else:
        creds = None

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            client_data = pathlib.Path(client_secrets_path).read_text(encoding="utf-8-sig")
            flow = InstalledAppFlow.from_client_config(json.loads(client_data), SCOPES)
            creds = flow.run_local_server(port=0)
        token_path.write_text(creds.to_json(), encoding="utf-8")

    return creds


@dataclass
class GoogleWorkspaceClient:
    credentials: Credentials

    def __post_init__(self) -> None:
        self.sheets_service = build("sheets", "v4", credentials=self.credentials, cache_discovery=False)
        self.drive_service = build("drive", "v3", credentials=self.credentials, cache_discovery=False)
        self.docs_service = build("docs", "v1", credentials=self.credentials, cache_discovery=False)

    def create_spreadsheet(self, title: str) -> dict[str, str]:
        response = self.sheets_service.spreadsheets().create(body={"properties": {"title": title}}).execute()
        spreadsheet_id = response["spreadsheetId"]
        self.ensure_tabs(spreadsheet_id)
        self.upsert_settings(spreadsheet_id, DEFAULT_SETTINGS)
        return {
            "spreadsheet_id": spreadsheet_id,
            "spreadsheet_url": response["spreadsheetUrl"],
        }

    def ensure_tabs(self, spreadsheet_id: str) -> None:
        spreadsheet = self.sheets_service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        existing_titles = {sheet["properties"]["title"] for sheet in spreadsheet.get("sheets", [])}
        requests: list[dict[str, Any]] = []

        for title in TAB_HEADERS:
            if title not in existing_titles:
                requests.append({"addSheet": {"properties": {"title": title}}})

        if requests:
            self.sheets_service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={"requests": requests},
            ).execute()

        for title, headers in TAB_HEADERS.items():
            self._write_headers_if_missing(spreadsheet_id, title, headers)

    def _write_headers_if_missing(self, spreadsheet_id: str, tab_name: str, headers: list[str]) -> None:
        existing = self.sheets_service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=f"'{tab_name}'!1:1",
        ).execute()
        current_values = existing.get("values", [])
        if current_values == [headers]:
            return
        self.sheets_service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"'{tab_name}'!1:1",
            valueInputOption="RAW",
            body={"values": [headers]},
        ).execute()

    def read_tab(self, spreadsheet_id: str, tab_name: str) -> list[dict[str, str]]:
        response = self.sheets_service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=f"'{tab_name}'",
        ).execute()
        values = response.get("values", [])
        if not values:
            return []
        headers = values[0]
        rows = []
        for row in values[1:]:
            record = {
                header: row[index] if index < len(row) else ""
                for index, header in enumerate(headers)
            }
            rows.append(record)
        return rows

    def replace_tab(self, spreadsheet_id: str, tab_name: str, rows: list[dict[str, Any]]) -> None:
        headers = TAB_HEADERS[tab_name]
        values = [headers] + [[self._stringify(row.get(header, "")) for header in headers] for row in rows]
        self.sheets_service.spreadsheets().values().clear(
            spreadsheetId=spreadsheet_id,
            range=f"'{tab_name}'",
            body={},
        ).execute()
        self.sheets_service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"'{tab_name}'!A1",
            valueInputOption="RAW",
            body={"values": values},
        ).execute()

    def append_rows(self, spreadsheet_id: str, tab_name: str, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        headers = TAB_HEADERS[tab_name]
        values = [[self._stringify(row.get(header, "")) for header in headers] for row in rows]
        self.sheets_service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=f"'{tab_name}'!A1",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": values},
        ).execute()

    def read_settings(self, spreadsheet_id: str) -> dict[str, str]:
        rows = self.read_tab(spreadsheet_id, "Settings")
        return {row["key"]: row["value"] for row in rows if row.get("key")}

    def upsert_settings(self, spreadsheet_id: str, settings: dict[str, Any]) -> None:
        current = self.read_settings(spreadsheet_id)
        current.update({key: self._stringify(value) for key, value in settings.items()})
        rows = [{"key": key, "value": value} for key, value in current.items()]
        self.replace_tab(spreadsheet_id, "Settings", rows)

    def share_file(self, file_id: str, email: str, role: str = "writer") -> None:
        self.drive_service.permissions().create(
            fileId=file_id,
            body={
                "type": "user",
                "role": role,
                "emailAddress": email,
            },
            sendNotificationEmail=False,
        ).execute()

    def move_file_to_folder(self, file_id: str, folder_id: str) -> None:
        metadata = self.drive_service.files().get(fileId=file_id, fields="parents").execute()
        previous_parents = ",".join(metadata.get("parents", []))
        self.drive_service.files().update(
            fileId=file_id,
            addParents=folder_id,
            removeParents=previous_parents,
            fields="id, parents",
        ).execute()

    def list_asset_files(self, root_folder_id: str) -> list[dict[str, str]]:
        folders = self.drive_service.files().list(
            q=f"'{root_folder_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false",
            fields="files(id, name)",
            pageSize=100,
        ).execute()["files"]

        rows: list[dict[str, str]] = []
        for folder in folders:
            files = self.drive_service.files().list(
                q=f"'{folder['id']}' in parents and mimeType != 'application/vnd.google-apps.folder' and trashed = false",
                fields="files(id, name, webViewLink)",
                pageSize=1000,
            ).execute()["files"]
            for item in files:
                rows.append({"folder": folder["name"], "name": item["name"], "webViewLink": item.get("webViewLink", "")})
        return rows

    @staticmethod
    def _stringify(value: Any) -> str:
        if isinstance(value, list):
            return ", ".join(str(item) for item in value)
        return "" if value is None else str(value)
