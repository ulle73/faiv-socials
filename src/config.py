from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


STOCKHOLM_TZ = ZoneInfo("Europe/Stockholm")
DEFAULT_SETTINGS = {
    "analysis_model": "openrouter/owl-alpha",
    "proposal_model": "z-ai/glm-5.2",
    "fallback_model": "meta-llama/llama-3.1-8b-instruct",
    "min_score": "60",
    "posts_per_account": "12",
    "notify_email": "",
    "active_batch": "A",
    "apify_actor_id": "apify/instagram-post-scraper",
}


class ConfigError(RuntimeError):
    pass


@dataclass(slots=True)
class AppConfig:
    apify_token: str
    openrouter_api_key: str
    google_client_secrets_path: str | None
    google_token_path: str | None
    spreadsheet_id: str | None
    output_folder_id: str | None
    asset_root_folder_id: str | None
    notify_email: str | None
    smtp_host: str | None
    smtp_port: int
    smtp_username: str | None
    smtp_password: str | None
    smtp_from: str | None
    r2_bucket: str | None = None
    r2_endpoint: str | None = None
    r2_access_key_id: str | None = None
    r2_secret_access_key: str | None = None
    r2_prefix: str | None = None
    cloudflare_account_id: str | None = None
    cloudflare_api_token: str | None = None
    cloudflare_d1_database_id: str | None = None
    timezone: ZoneInfo = STOCKHOLM_TZ


@dataclass(slots=True)
class RuntimeSettings:
    analysis_model: str
    proposal_model: str
    fallback_model: str
    min_score: int
    posts_per_account: int
    notify_email: str
    active_batch: str
    apify_actor_id: str

    @classmethod
    def from_sheet(cls, values: dict[str, str], app_config: AppConfig) -> "RuntimeSettings":
        merged = {**DEFAULT_SETTINGS, **values}
        notify_email = (merged.get("notify_email") or app_config.notify_email or "").strip()
        if not notify_email:
            raise ConfigError("Settings saknar notify_email. Sätt värdet i Settings-fliken eller NOTIFY_EMAIL.")

        return cls(
            analysis_model=merged["analysis_model"],
            proposal_model=merged["proposal_model"],
            fallback_model=merged["fallback_model"],
            min_score=int(merged["min_score"]),
            posts_per_account=int(merged["posts_per_account"]),
            notify_email=notify_email,
            active_batch=merged.get("active_batch", "A"),
            apify_actor_id=merged.get("apify_actor_id", DEFAULT_SETTINGS["apify_actor_id"]),
        )


def load_app_config(
    required_secrets: tuple[str, ...] = ("APIFY_TOKEN", "OPENROUTER_API_KEY", "GOOGLE_CLIENT_SECRETS_FILE"),
) -> AppConfig:
    dotenv_values = load_dotenv_values()
    config_values = {**dotenv_values, **os.environ}
    missing = [
        name
        for name in required_secrets
        if not config_values.get(name)
    ]
    if missing:
        joined = ", ".join(missing)
        raise ConfigError(f"Saknade secrets: {joined}. Lägg in dem i GitHub Actions-secrets eller din lokala miljö.")

    return AppConfig(
        apify_token=config_values.get("APIFY_TOKEN", ""),
        openrouter_api_key=config_values.get("OPENROUTER_API_KEY", ""),
        google_client_secrets_path=config_values.get("GOOGLE_CLIENT_SECRETS_FILE"),
        google_token_path=config_values.get("GOOGLE_TOKEN_FILE", ".google_token.json"),
        spreadsheet_id=config_values.get("GOOGLE_SPREADSHEET_ID"),
        output_folder_id=config_values.get("GOOGLE_OUTPUT_FOLDER_ID"),
        asset_root_folder_id=config_values.get("GOOGLE_ASSET_ROOT_FOLDER_ID"),
        notify_email=config_values.get("NOTIFY_EMAIL"),
        smtp_host=config_values.get("SMTP_HOST"),
        smtp_port=int(config_values.get("SMTP_PORT", "587")),
        smtp_username=config_values.get("SMTP_USERNAME"),
        smtp_password=config_values.get("SMTP_PASSWORD"),
        smtp_from=config_values.get("SMTP_FROM"),
        r2_bucket=resolve_r2_bucket(config_values),
        r2_endpoint=resolve_r2_endpoint(config_values),
        r2_access_key_id=first_present(config_values, "R2_ACCESS_KEY_ID", "S3_ACCESS_KEY_ID"),
        r2_secret_access_key=first_present(config_values, "R2_SECRET_ACCESS_KEY", "S3_SECRET_ACCESS_KEY"),
        r2_prefix=first_present(config_values, "R2_PREFIX", "S3_PREFIX") or "apify/raw",
        cloudflare_account_id=first_present(config_values, "CLOUDFLARE_ACCOUNT_ID"),
        cloudflare_api_token=first_present(config_values, "CLOUDFLARE_API_TOKEN"),
        cloudflare_d1_database_id=first_present(config_values, "CLOUDFLARE_D1_DATABASE_ID"),
    )


def today_stockholm() -> datetime:
    return datetime.now(tz=STOCKHOLM_TZ)


def load_dotenv_values(path: str | Path = ".env") -> dict[str, str]:
    dotenv_path = Path(path)
    if not dotenv_path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        normalized_key = key.strip().lstrip("\ufeff")
        normalized_value = value.strip()
        if (
            len(normalized_value) >= 2
            and normalized_value[0] == normalized_value[-1]
            and normalized_value[0] in {"'", '"'}
        ):
            normalized_value = normalized_value[1:-1]
        values[normalized_key] = normalized_value
    return values


def first_present(values: dict[str, str], *keys: str) -> str | None:
    for key in keys:
        candidate = (values.get(key) or "").strip()
        if candidate:
            return candidate
    return None


def resolve_r2_endpoint(values: dict[str, str]) -> str | None:
    endpoint = first_present(values, "R2_ENDPOINT", "S3_ENDPOINT", "S3_API")
    if endpoint:
        normalized = endpoint.strip().rstrip("/")
        if normalized.startswith("http://") or normalized.startswith("https://"):
            return normalized
        return f"https://{normalized.lstrip('/')}"

    account_id = first_present(values, "R2_ACCOUNT_ID")
    if account_id:
        return f"https://{account_id}.r2.cloudflarestorage.com"

    return None


def resolve_r2_bucket(values: dict[str, str]) -> str | None:
    bucket = first_present(values, "R2_BUCKET", "R2_BUCKET_NAME", "S3_BUCKET", "S3_BUCKET_NAME")
    if bucket:
        return bucket

    endpoint = resolve_r2_endpoint(values)
    if not endpoint:
        return None

    endpoint_without_scheme = endpoint.split("://", 1)[-1]
    if "/" not in endpoint_without_scheme:
        return None

    path_value = endpoint_without_scheme.split("/", 1)[-1].strip("/")
    if path_value:
        return path_value.split("/")[0]

    return None

