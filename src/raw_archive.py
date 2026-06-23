from __future__ import annotations

import gzip
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from src.config import AppConfig, ConfigError


class RawArchive(Protocol):
    def archive_apify_payload(
        self,
        *,
        items: list[dict[str, Any]],
        actor_id: str,
        batch_date: str,
        source_handles: list[str],
    ) -> str: ...


@dataclass(slots=True)
class R2RawArchiveClient:
    bucket: str
    endpoint: str
    access_key_id: str
    secret_access_key: str
    prefix: str = "apify/raw"
    s3_client: Any | None = None

    def __post_init__(self) -> None:
        if self.s3_client is None:
            self.s3_client = create_s3_client(
                endpoint=self.endpoint,
                access_key_id=self.access_key_id,
                secret_access_key=self.secret_access_key,
            )

    def archive_apify_payload(
        self,
        *,
        items: list[dict[str, Any]],
        actor_id: str,
        batch_date: str,
        source_handles: list[str],
    ) -> str:
        object_key = build_archive_key(
            prefix=self.prefix,
            batch_date=batch_date,
            actor_id=actor_id,
            source_handles=source_handles,
            item_count=len(items),
        )
        payload = {
            "archived_at": datetime.now(timezone.utc).isoformat(),
            "actor_id": actor_id,
            "batch_date": batch_date,
            "source_handles": source_handles,
            "item_count": len(items),
            "items": items,
        }
        body = gzip.compress(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        self.s3_client.put_object(
            Bucket=self.bucket,
            Key=object_key,
            Body=body,
            ContentType="application/json",
            ContentEncoding="gzip",
        )
        return object_key


def build_raw_archive_client(app_config: AppConfig) -> R2RawArchiveClient | None:
    configured_values = [
        app_config.r2_bucket,
        app_config.r2_endpoint,
        app_config.r2_access_key_id,
        app_config.r2_secret_access_key,
    ]
    if not any(configured_values):
        return None

    missing = []
    if not app_config.r2_bucket:
        missing.append("R2_BUCKET")
    if not app_config.r2_endpoint:
        missing.append("R2_ENDPOINT eller R2_ACCOUNT_ID")
    if not app_config.r2_access_key_id:
        missing.append("R2_ACCESS_KEY_ID")
    if not app_config.r2_secret_access_key:
        missing.append("R2_SECRET_ACCESS_KEY")
    if missing:
        raise ConfigError(
            "R2-konfigurationen är ofullständig. Lägg in följande i .env/GitHub Secrets: "
            + ", ".join(missing)
            + "."
        )

    if looks_like_r2_endpoint_host(app_config.r2_bucket):
        raise ConfigError(
            "R2_BUCKET ser ut att innehålla en endpoint-host i stället för bucket-namnet. "
            "Ange endast själva bucket-namnet i R2_BUCKET."
        )

    return R2RawArchiveClient(
        bucket=app_config.r2_bucket,
        endpoint=app_config.r2_endpoint,
        access_key_id=app_config.r2_access_key_id,
        secret_access_key=app_config.r2_secret_access_key,
        prefix=app_config.r2_prefix or "apify/raw",
    )


def build_archive_key(
    *,
    prefix: str,
    batch_date: str,
    actor_id: str,
    source_handles: list[str],
    item_count: int,
) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    normalized_prefix = prefix.strip("/") or "apify/raw"
    safe_actor = actor_id.replace("/", "-").replace("~", "-")
    handle_seed = ",".join(sorted(source_handles))
    digest = hashlib.sha1(f"{timestamp}|{safe_actor}|{handle_seed}|{item_count}".encode("utf-8")).hexdigest()[:12]
    date_path = batch_date.replace("-", "/")
    return f"{normalized_prefix}/{date_path}/{safe_actor}-{timestamp}-{digest}.json.gz"


def create_s3_client(*, endpoint: str, access_key_id: str, secret_access_key: str):
    import boto3
    from botocore.config import Config as BotoConfig

    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
        region_name="auto",
        config=BotoConfig(signature_version="s3v4"),
    )


def looks_like_r2_endpoint_host(value: str | None) -> bool:
    normalized = (value or "").strip().lower()
    return normalized.endswith(".r2.cloudflarestorage.com") or normalized == "r2.cloudflarestorage.com"
