from __future__ import annotations

import json
from typing import Iterable

import requests

from src.config import FAIV_CONTENT_CATEGORIES, SERVICE_AREAS
from src.models import CandidatePost, CollectedPost
from src.utils import chunked, parse_json_payload


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


class OpenRouterClient:
    def __init__(self, api_key: str, session: requests.Session | None = None) -> None:
        self.api_key = api_key
        self.session = session or requests.Session()

    def structured_chat(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        schema_name: str,
        schema: dict,
        temperature: float = 0.2,
    ) -> str:
        payload = {
            "model": model,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "strict": True,
                    "schema": schema,
                },
            },
        }
        response = self.session.post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "X-Title": "FAIV Socials",
            },
            json=payload,
            timeout=120,
        )
        if response.status_code >= 400:
            fallback_payload = {
                **payload,
                "response_format": {"type": "json_object"},
            }
            response = self.session.post(
                OPENROUTER_URL,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "X-Title": "FAIV Socials",
                },
                json=fallback_payload,
                timeout=120,
            )
        response.raise_for_status()
        body = response.json()
        content = body["choices"][0]["message"]["content"]
        if isinstance(content, list):
            return "\n".join(part.get("text", "") for part in content if isinstance(part, dict))
        return content


def analysis_schema() -> dict:
    return {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "faiv_fit": {"type": "integer"},
                "lead_potential": {"type": "integer"},
                "hook_strength": {"type": "integer"},
                "visual_transferability": {"type": "integer"},
                "novelty": {"type": "integer"},
                "total": {"type": "integer"},
                "faiv_content_category": {"type": "string"},
                "service_area": {"type": "string"},
                "why_it_works": {"type": "string"},
                "originality_risk": {"type": "string"},
            },
            "required": [
                "url",
                "faiv_fit",
                "lead_potential",
                "hook_strength",
                "visual_transferability",
                "novelty",
                "total",
                "faiv_content_category",
                "service_area",
                "why_it_works",
                "originality_risk",
            ],
            "additionalProperties": False,
        },
    }


def build_analysis_prompt(posts: Iterable[CollectedPost]) -> str:
    serialized_posts = [
        {
            "url": post.post_url,
            "source": post.source_handle,
            "caption": post.caption,
            "caption_first_line": post.caption_first_line,
            "post_type": post.post_type,
            "hook_signal": post.hook_signal,
            "media_count": len(post.media_urls),
            "likes": post.likes_count,
            "comments": post.comments_count,
            "engagement": post.engagement_count,
            "hashtags": post.hashtags,
            "has_cta": post.has_cta,
            "has_question": post.has_question,
            "has_emoji": post.has_emoji,
            "is_image": post.is_image,
            "is_carousel": post.is_carousel,
            "is_video": post.is_video,
            "caption_length": post.caption_length,
            "published_age_hours": post.published_age_hours_at_collect,
        }
        for post in posts
    ]
    return (
        "Du ar FAIVs innehallsanalytiker. Bedom dessa Instagram-poster for hur val de kan bli svenska FAIV-inlagg. "
        "FAIV saljer grillkit, extrabelysning, arbetsljus, bilinredning, servicebilar och husbil/offgrid till svenska fordonsagare. "
        "Anvand all tillganglig data: engagement (likes, kommentarer), hashtaggar, hook-signal, post-typ och caption for att bedoma. "
        "Ranka inte pa popularitet -- ranka pa om inlagget kan bli ett svenskt, offertdrivande FAIV-inlagg.\n\n"
        "VIKTIGA KATEGORIREGLER:\n"
        "faiv_content_category far endast vara en av: "
        + ", ".join(FAIV_CONTENT_CATEGORIES)
        + ".\n"
        "service_area ska vara ett separat falt och far vara: "
        + ", ".join(SERVICE_AREAS)
        + ".\n"
        "faiv_content_category far ALDRIG vara 'servicebil', 'extrabelysning', 'arbetsljus', 'grillkit', 'verkstad' eller annat tjanteomrade.\n"
        "service_area far ALDRIG vara 'Forvandlingar', 'Kundbyggen', 'Ratt val' eller 'Bakom bygget'.\n"
        "Returnera bara JSON enligt schemat.\n\nPoster:\n"
        f"{json.dumps(serialized_posts, ensure_ascii=False, indent=2)}"
    )


def parse_analysis_response(
    raw_response: str,
    post_lookup: dict[str, CollectedPost],
    min_score: int,
) -> list[CandidatePost]:
    rows = parse_json_payload(raw_response)
    candidates: list[CandidatePost] = []

    for row in rows:
        if int(row["total"]) < min_score:
            continue
        source_post = post_lookup.get(row["url"])
        if source_post is None:
            continue
        candidates.append(
            CandidatePost(
                source_post=source_post,
                faiv_fit=int(row["faiv_fit"]),
                lead_potential=int(row["lead_potential"]),
                hook_strength=int(row["hook_strength"]),
                visual_transferability=int(row["visual_transferability"]),
                novelty=int(row["novelty"]),
                total_score=int(row["total"]),
                faiv_content_category=row["faiv_content_category"],
                service_area=row.get("service_area", "ovrigt"),
                why_it_works=row["why_it_works"],
                originality_risk=row["originality_risk"],
            )
        )

    return sorted(candidates, key=lambda candidate: candidate.total_score, reverse=True)


def analyze_posts(
    posts: Iterable[CollectedPost],
    *,
    min_score: int,
    model: str,
    client: OpenRouterClient,
) -> list[CandidatePost]:
    post_list = list(posts)
    candidates: list[CandidatePost] = []
    for batch in chunked(post_list, 20):
        raw_response = client.structured_chat(
            model=model,
            system_prompt="Du returnerar strikt JSON och fokuserar pa svensk B2B/B2C-relevans for FAIV. faiv_content_category ar alltid en av de fyra innehallskategorierna, service_area ar alltid ett tjanteomrade.",
            user_prompt=build_analysis_prompt(batch),
            schema_name="faiv_analysis_batch",
            schema=analysis_schema(),
        )
        lookup = {post.post_url: post for post in batch}
        candidates.extend(parse_analysis_response(raw_response, lookup, min_score=min_score))
    return sorted(candidates, key=lambda candidate: candidate.total_score, reverse=True)
