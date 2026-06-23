from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

import requests

from src.models import CollectedPost, SourceAccount
from src.raw_archive import RawArchive


APIFY_BASE_URL = "https://api.apify.com/v2"
CTA_MARKERS = (
    "hör av dig",
    "kontakta",
    "skicka",
    "maila",
    "ring",
    "beställ",
    "boka",
    "offert",
    "dm",
    "skriv till oss",
)


@dataclass(slots=True)
class CollectionOutcome:
    posts: list[CollectedPost]
    blocked_accounts: list[str]
    warnings: list[str]
    updated_sources: list[SourceAccount]
    raw_archive_key: str | None = None


class ApifyCollector:
    def __init__(
        self,
        api_token: str,
        actor_id: str,
        session: requests.Session | None = None,
        raw_archive: RawArchive | None = None,
    ) -> None:
        self.api_token = api_token
        self.actor_id = actor_id.replace("/", "~")
        self.session = session or requests.Session()
        self.raw_archive = raw_archive

    def collect_posts_for_sources(
        self,
        sources: Iterable[SourceAccount],
        posts_per_account: int,
        batch_date: str,
        existing_urls: set[str],
        throttle_seconds: float = 2.0,
        only_posts_newer_than: dict[str, str] | None = None,
    ) -> CollectionOutcome:
        source_list = list(sources)
        collected: list[CollectedPost] = []
        blocked_accounts: list[str] = []
        warnings: list[str] = []
        updated_sources: list[SourceAccount] = source_list
        raw_archive_key: str | None = None

        if not source_list:
            return CollectionOutcome(
                posts=[],
                blocked_accounts=[],
                warnings=[],
                updated_sources=[],
                raw_archive_key=None,
            )

        try:
            payload = build_actor_input(source_list, posts_per_account=posts_per_account, only_posts_newer_than=only_posts_newer_than)
            collected_at = datetime.now(timezone.utc)
            response = self.session.post(
                f"{APIFY_BASE_URL}/acts/{self.actor_id}/run-sync-get-dataset-items",
                params={"token": self.api_token, "clean": "1", "format": "json"},
                json=payload,
                timeout=300,
            )
            response.raise_for_status()
            items = response.json()
            if self.raw_archive is not None:
                raw_archive_key = self.raw_archive.archive_apify_payload(
                    items=items,
                    actor_id=self.actor_id,
                    batch_date=batch_date,
                    source_handles=[username_for_source(source) for source in source_list],
                )
            posts = normalize_post_items(
                items,
                source_list,
                batch_date,
                raw_archive_key=raw_archive_key,
                collected_at=collected_at,
            )
            deduped = dedupe_posts(posts, existing_urls)
            collected.extend(deduped)
            returned_handles = {post.source_handle.casefold() for post in deduped}

            for source in source_list:
                source_key = username_for_source(source).casefold()
                if source_key in returned_handles:
                    source.status = "ok"
                    source.last_fetched = batch_date
                else:
                    source.status = "tom"
        except requests.HTTPError as error:
            status_code = error.response.status_code if error.response else None
            for source in source_list:
                source.status = "fel"
            warnings.append(f"Apify HTTP-fel {status_code or 'okänt'}: {error}")
        except Exception as error:  # noqa: BLE001
            for source in source_list:
                source.status = "fel"
            warnings.append(f"Apify-anrop misslyckades: {error}")

        if throttle_seconds > 0:
            time.sleep(throttle_seconds + random.uniform(0.0, 1.0))

        return CollectionOutcome(
            posts=collected,
            blocked_accounts=blocked_accounts,
            warnings=warnings,
            updated_sources=updated_sources,
            raw_archive_key=raw_archive_key,
        )


def build_actor_input(
    sources: Iterable[SourceAccount],
    posts_per_account: int,
    only_posts_newer_than: dict[str, str] | None = None,
) -> dict:
    input_dict: dict = {
        "dataDetailLevel": "basicData",
        "resultsLimit": posts_per_account,
        "skipPinnedPosts": False,
        "username": [username_for_source(source) for source in sources],
    }
    if only_posts_newer_than:
        cutoff_dates = list({date for date in only_posts_newer_than.values() if date})
        if len(cutoff_dates) == 1:
            input_dict["onlyPostsNewerThan"] = cutoff_dates[0]
        elif len(cutoff_dates) > 1:
            input_dict["onlyPostsNewerThan"] = min(cutoff_dates)
    return input_dict


def username_for_source(source: SourceAccount) -> str:
    raw_value = (source.handle or source.lookup_term or "").strip()
    if raw_value.startswith("http://") or raw_value.startswith("https://"):
        stripped = raw_value.rstrip("/").split("/")[-1]
        return stripped.lstrip("@")
    return raw_value.lstrip("@").strip("/")


def normalize_post_item(
    source: SourceAccount,
    item: dict,
    batch_date: str,
    raw_archive_key: str | None = None,
    run_id: str = "",
    collected_at: datetime | None = None,
) -> CollectedPost:
    media_urls: list[str] = []
    for key in ("displayUrl", "imageUrl", "videoUrl", "thumbnailUrl"):
        value = item.get(key)
        if value:
            media_urls.append(value)
    for image in item.get("images", []) or []:
        if isinstance(image, str):
            media_urls.append(image)
        elif isinstance(image, dict):
            candidate = image.get("url") or image.get("displayUrl")
            if candidate:
                media_urls.append(candidate)

    post_url = item.get("url") or item.get("inputUrl") or item.get("postUrl")
    caption = (item.get("caption") or item.get("text") or "").strip()
    published_raw = (
        item.get("timestamp")
        or item.get("takenAtTimestamp")
        or item.get("latestComments") and item.get("latestComments")[0].get("timestamp")
        or ""
    )
    published_at = normalize_datetime_string(published_raw)
    post_type = item.get("type") or item.get("productType") or item.get("__typename") or "unknown"
    hook_signal = caption[:120] if caption else source.company_name
    hashtags = extract_hashtags(item, caption)
    likes_count = to_int(item.get("likesCount"))
    comments_count = to_int(item.get("commentsCount"))
    engagement_count = likes_count + comments_count
    caption_first_line = next((line.strip() for line in caption.splitlines() if line.strip()), "")
    is_video = detect_video(post_type, item)
    is_carousel = detect_carousel(post_type, item, media_urls)
    is_image = not is_video and not is_carousel and detect_image(post_type, item, media_urls)
    source_handle = source.handle or source.lookup_term
    owner_username = str(item.get("ownerUsername") or source_handle).strip()
    collected_dt = collected_at or datetime.now(timezone.utc)

    return CollectedPost(
        source_handle=source_handle,
        post_url=post_url,
        published_at=published_at,
        caption=caption,
        post_type=str(post_type),
        media_urls=list(dict.fromkeys(media_urls)),
        hook_signal=hook_signal,
        batch_date=batch_date,
        raw_archive_key=raw_archive_key,
        raw_payload=item,
        run_id=run_id,
        instagram_post_id=str(item.get("id") or ""),
        short_code=str(item.get("shortCode") or item.get("code") or ""),
        owner_id=str(item.get("ownerId") or ""),
        owner_username=owner_username,
        owner_full_name=str(item.get("ownerFullName") or source.company_name or ""),
        likes_count=likes_count,
        comments_count=comments_count,
        is_comments_disabled=bool(item.get("isCommentsDisabled") is True),
        hashtags=hashtags,
        dimensions_width=to_optional_int(item.get("dimensionsWidth")),
        dimensions_height=to_optional_int(item.get("dimensionsHeight")),
        engagement_count=engagement_count,
        caption_length=len(caption),
        hashtag_count=len(hashtags),
        published_age_hours_at_collect=compute_age_hours(published_raw, collected_dt),
        caption_first_line=caption_first_line,
        has_cta=contains_cta(caption),
        has_question="?" in caption,
        has_emoji=contains_emoji(caption),
        is_image=is_image,
        is_carousel=is_carousel,
        is_video=is_video,
    )


def normalize_post_items(
    items: Iterable[dict],
    sources: Iterable[SourceAccount],
    batch_date: str,
    raw_archive_key: str | None = None,
    run_id: str = "",
    collected_at: datetime | None = None,
) -> list[CollectedPost]:
    source_lookup = {
        username_for_source(source).casefold(): source
        for source in sources
    }
    normalized_posts: list[CollectedPost] = []

    for item in items:
        if item.get("noResults") is True:
            continue
        owner_username = str(item.get("ownerUsername") or "").strip().casefold()
        source = source_lookup.get(owner_username)
        if source is None:
            continue
        normalized_posts.append(
            normalize_post_item(
                source,
                item,
                batch_date,
                raw_archive_key=raw_archive_key,
                run_id=run_id,
                collected_at=collected_at,
            )
        )

    return normalized_posts


def dedupe_posts(posts: Iterable[CollectedPost], existing_urls: set[str]) -> list[CollectedPost]:
    seen = set(existing_urls)
    deduped: list[CollectedPost] = []
    for post in posts:
        if not post.post_url or post.post_url in seen:
            continue
        seen.add(post.post_url)
        deduped.append(post)
    return deduped


def normalize_datetime_string(value: object) -> str:
    parsed = parse_datetime_value(value)
    if parsed is not None:
        return parsed.isoformat()
    return str(value or "")


def parse_datetime_value(value: object) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)

    text = str(value).strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        if text.isdigit():
            return datetime.fromtimestamp(float(text), tz=timezone.utc)
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def to_int(value: object) -> int:
    try:
        if value is None or value == "":
            return 0
        return int(value)
    except (TypeError, ValueError):
        return 0


def to_optional_int(value: object) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def extract_hashtags(item: dict, caption: str) -> list[str]:
    raw_hashtags = item.get("hashtags")
    if isinstance(raw_hashtags, list):
        values: list[str] = []
        for entry in raw_hashtags:
            if isinstance(entry, str):
                hashtag = entry.strip().lstrip("#")
            elif isinstance(entry, dict):
                hashtag = str(entry.get("name") or entry.get("tag") or "").strip().lstrip("#")
            else:
                hashtag = ""
            if hashtag:
                values.append(hashtag)
        return list(dict.fromkeys(values))

    extracted = re.findall(r"#([\wåäöÅÄÖ]+)", caption)
    return list(dict.fromkeys(extracted))


def compute_age_hours(published_value: object, collected_at: datetime) -> int | None:
    published_at = parse_datetime_value(published_value)
    if published_at is None:
        return None
    delta = collected_at.astimezone(timezone.utc) - published_at
    return max(0, int(delta.total_seconds() // 3600))


def contains_cta(caption: str) -> bool:
    lowered = caption.casefold()
    return any(marker in lowered for marker in CTA_MARKERS)


def contains_emoji(text: str) -> bool:
    for character in text:
        codepoint = ord(character)
        if (
            0x1F300 <= codepoint <= 0x1FAFF
            or 0x2600 <= codepoint <= 0x27BF
            or 0x1F1E6 <= codepoint <= 0x1F1FF
        ):
            return True
    return False


def detect_video(post_type: object, item: dict) -> bool:
    normalized = str(post_type or "").strip().casefold()
    return normalized in {"video", "reel", "igtv", "clips", "graphvideo"} or bool(item.get("videoUrl"))


def detect_carousel(post_type: object, item: dict, media_urls: list[str]) -> bool:
    normalized = str(post_type or "").strip().casefold()
    return normalized in {"sidecar", "carousel", "graphsidecar"} or len(media_urls) > 1


def detect_image(post_type: object, item: dict, media_urls: list[str]) -> bool:
    normalized = str(post_type or "").strip().casefold()
    return normalized in {"image", "photo", "graphimage"} or bool(item.get("displayUrl")) or bool(media_urls)
