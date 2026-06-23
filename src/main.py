from __future__ import annotations

import argparse
from pathlib import Path

from src.config import AppConfig, ConfigError, load_app_config
from src.ingest import run_collection_only
from src.pipeline import bootstrap_workspace, run_pipeline, sync_asset_library
from src.sheets import GoogleWorkspaceClient, load_credentials


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="FAIV social media automation")
    parser.add_argument(
        "--watchlist",
        default="faiv-sociala-medier-watchlist.md",
        help="Path to the watchlist markdown file.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    login = subparsers.add_parser("login", help="Authenticate with Google via OAuth and save token.")
    login.add_argument(
        "--client-secrets",
        default=None,
        help="Path to Google OAuth client secrets JSON. Defaults to GOOGLE_CLIENT_SECRETS_FILE from env.",
    )

    bootstrap = subparsers.add_parser("bootstrap", help="Create or initialize the Google Sheet control panel.")
    bootstrap.add_argument("--title", default="FAIV Sociala Medier", help="Spreadsheet title if a new sheet is created.")

    collect_only = subparsers.add_parser(
        "collect-only",
        help="Collect from Apify and store only in R2 + D1 without OpenRouter, Google Sheets or Docs.",
    )
    collect_only.add_argument("--batch", default="A", help="Batch to collect when handles are not specified.")
    collect_only.add_argument("--posts-per-account", type=int, default=1, help="Max posts per account for collection.")
    collect_only.add_argument(
        "--handles",
        nargs="*",
        help="Optional explicit Instagram handles to collect instead of the assigned batch.",
    )
    collect_only.add_argument(
        "--throttle-seconds",
        type=float,
        default=2.0,
        help="Throttle time after the batch request.",
    )

    subparsers.add_parser("sync-assets", help="Refresh Asset Library from Google Drive.")
    subparsers.add_parser("run", help="Execute one pipeline run.")
    return parser


def _build_workspace_client(app_config: AppConfig) -> GoogleWorkspaceClient:
    if not app_config.google_client_secrets_path:
        raise ConfigError(
            "GOOGLE_CLIENT_SECRETS_FILE saknas. Ladda ner OAuth client secrets från Google Cloud Console "
            "och sätt sökvägen i .env eller som miljövariabel."
        )
    creds = load_credentials(
        client_secrets_path=app_config.google_client_secrets_path,
        token_path=app_config.google_token_path,
    )
    return GoogleWorkspaceClient(creds)


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        watchlist_path = Path(args.watchlist)

        if args.command == "login":
            app_config = load_app_config(required_secrets=())
            secrets_path = args.client_secrets or app_config.google_client_secrets_path
            if not secrets_path:
                raise ConfigError(
                    "Ingen client secrets-sökväg angiven. Använd --client-secrets eller sätt GOOGLE_CLIENT_SECRETS_FILE."
                )
            creds = load_credentials(
                client_secrets_path=secrets_path,
                token_path=app_config.google_token_path,
            )
            print(f"Google-inloggning klar. Token sparad i {app_config.google_token_path or '.google_token.json'}")
            print(f"Inloggad som: {creds.client_id}")
            return 0

        if args.command == "collect-only":
            app_config = load_app_config(required_secrets=("APIFY_TOKEN",))
            summary = run_collection_only(
                app_config=app_config,
                watchlist_path=watchlist_path,
                batch=args.batch,
                posts_per_account=args.posts_per_account,
                handles=args.handles,
                throttle_seconds=args.throttle_seconds,
            )
            print(
                f"Collect klar: {summary.collected_count} hämtade till R2/D1, "
                f"källor={summary.source_count}, run_id={summary.run_id}, raw={summary.raw_archive_key or 'ingen'}"
            )
            return 0

        app_config = load_app_config()
        workspace_client = _build_workspace_client(app_config)

        if args.command == "bootstrap":
            if app_config.spreadsheet_id:
                spreadsheet_id = app_config.spreadsheet_id
            else:
                created = workspace_client.create_spreadsheet(args.title)
                spreadsheet_id = created["spreadsheet_id"]
                print(f"Skapade spreadsheet: {created['spreadsheet_url']}")
                print("Spara spreadsheet-id i GOOGLE_SPREADSHEET_ID innan schemalagd drift.")
            bootstrap_workspace(
                workspace_client,
                spreadsheet_id=spreadsheet_id,
                watchlist_path=watchlist_path,
                notify_email=app_config.notify_email or "",
            )
            if app_config.asset_root_folder_id:
                count = sync_asset_library(workspace_client, spreadsheet_id, app_config.asset_root_folder_id)
                print(f"Synkade {count} asset-rader från Drive.")
            print("Bootstrap klar.")
            return 0

        if not app_config.spreadsheet_id:
            raise ConfigError("GOOGLE_SPREADSHEET_ID saknas. Kör bootstrap först.")

        if args.command == "sync-assets":
            if not app_config.asset_root_folder_id:
                raise ConfigError("GOOGLE_ASSET_ROOT_FOLDER_ID saknas.")
            count = sync_asset_library(workspace_client, app_config.spreadsheet_id, app_config.asset_root_folder_id)
            print(f"Synkade {count} asset-rader från Drive.")
            return 0

        summary = run_pipeline(
            app_config=app_config,
            workspace_client=workspace_client,
            watchlist_path=watchlist_path,
        )
        print(
            f"Klar: {summary.collected_count} hämtade, {summary.candidate_count} kandidater, "
            f"{summary.proposal_count} förslag, doc={summary.doc_url or 'ingen'}"
        )
        return 0
    except ConfigError as error:
        print(f"Konfigurationsfel: {error}")
        return 2
    except Exception as error:  # noqa: BLE001
        print(f"Körningen misslyckades: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

