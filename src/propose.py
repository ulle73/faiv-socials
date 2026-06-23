from __future__ import annotations

import json
from typing import Iterable

from src.analyze import OpenRouterClient
from src.models import CandidatePost, Proposal
from src.utils import parse_json_payload


REQUIRED_PROPOSAL_FIELDS = {
    "source_url",
    "hook",
    "caption",
    "cta",
    "format",
    "image_brief",
    "recommended_asset_folder",
    "fallback_image_prompt",
    "why_selected",
}


def proposal_schema() -> dict:
    return {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "source_url": {"type": "string"},
                "hook": {"type": "string"},
                "caption": {"type": "string"},
                "cta": {"type": "string"},
                "format": {"type": "string"},
                "image_brief": {"type": "string"},
                "recommended_asset_folder": {"type": "string"},
                "fallback_image_prompt": {"type": "string"},
                "why_selected": {"type": "string"},
            },
            "required": list(REQUIRED_PROPOSAL_FIELDS),
            "additionalProperties": False,
        },
    }


def build_proposal_prompt(candidates: Iterable[CandidatePost]) -> str:
    payload = [
        {
            "source_url": candidate.source_post.post_url,
            "source_account": candidate.source_post.source_handle,
            "caption_first_line": candidate.source_post.caption_first_line[:120],
            "category": candidate.faiv_category,
            "why_it_works": candidate.why_it_works,
            "originality_risk": candidate.originality_risk,
        }
        for candidate in candidates
    ]
    return (
        "Skapa färdiga svenska FAIV-förslag för Instagram/Facebook. "
        "Varje förslag ska vara en ny FAIV-vinkel, inte en omskrivning rad för rad. "
        "Hooks max två rader. Captions max 120 ord. Returnera bara JSON enligt schemat.\n\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def parse_proposal_response(raw_response: str) -> list[dict[str, str]]:
    rows = parse_json_payload(raw_response)
    proposals: list[dict[str, str]] = []

    for row in rows:
        missing = REQUIRED_PROPOSAL_FIELDS - row.keys()
        if missing:
            missing_fields = ", ".join(sorted(missing))
            raise ValueError(f"Proposal output missing required fields: {missing_fields}")
        proposals.append({field: str(row[field]).strip() for field in REQUIRED_PROPOSAL_FIELDS})
    return proposals


def generate_proposals(
    candidates: Iterable[CandidatePost],
    *,
    model: str,
    fallback_model: str,
    client: OpenRouterClient,
) -> list[Proposal]:
    candidate_list = list(candidates)
    if not candidate_list:
        return []
    raw_response = client.structured_chat(
        model=model or fallback_model,
        system_prompt="Du skriver svensk social copy för FAIV och returnerar strikt JSON.",
        user_prompt=build_proposal_prompt(candidate_list),
        schema_name="faiv_proposals",
        schema=proposal_schema(),
        temperature=0.4,
    )
    rows = parse_proposal_response(raw_response)
    candidate_lookup = {candidate.source_post.post_url: candidate for candidate in candidate_list}
    proposals: list[Proposal] = []

    for row in rows:
        source_candidate = candidate_lookup.get(row["source_url"])
        if source_candidate is None:
            continue
        proposals.append(
            Proposal(
                source_candidate=source_candidate,
                hook=row["hook"],
                caption=row["caption"],
                cta=row["cta"],
                format=row["format"],
                image_brief=row["image_brief"],
                recommended_asset_folder=row["recommended_asset_folder"],
                fallback_image_prompt=row["fallback_image_prompt"],
                why_selected=row["why_selected"],
            )
        )

    return proposals
