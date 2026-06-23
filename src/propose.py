from __future__ import annotations

import json
from typing import Iterable

from src.analyze import OpenRouterClient
from src.config import (
    ALLOWED_CTAS,
    APPROVED_PRODUCTS,
    DEFAULT_FEED_FORMAT,
    DEFAULT_STORY_FORMAT,
    FAIV_CONTENT_CATEGORIES,
    FORBIDDEN_COPY_PHRASES,
    MIN_AI_PROMPT_LENGTH,
    PROPOSAL_STATUSES,
    SERVICE_AREAS,
)
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
    "faiv_content_category",
    "service_area",
    "overlay_text",
    "image_plan",
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
                "faiv_content_category": {"type": "string"},
                "service_area": {"type": "string"},
                "overlay_text": {"type": "string"},
                "carousel_structure": {"type": "array", "items": {"type": "object"}},
                "image_plan": {"type": "string"},
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
            "faiv_content_category": candidate.faiv_content_category,
            "service_area": candidate.service_area,
            "why_it_works": candidate.why_it_works,
            "originality_risk": candidate.originality_risk,
        }
        for candidate in candidates
    ]
    return (
        "Skapa fardiga svenska FAIV-postpaket for Instagram/Facebook. "
        "Varje forslag ska vara en ny FAIV-vinkel, inte en omskrivning rad for rad.\n\n"
        "KATEGORIREGLER:\n"
        "faiv_content_category far endast vara en av: " + ", ".join(FAIV_CONTENT_CATEGORIES) + ".\n"
        "service_area far endast vara ett av: " + ", ".join(SERVICE_AREAS) + ".\n"
        "faiv_content_category far ALDRIG vara 'servicebil', 'extrabelysning', 'arbetsljus' eller annat tjanteomrade.\n\n"
        "SANNINGSREGLER:\n"
        "Skriv ALDRIG 'vi monterade', 'vi byggde', 'vi utrustade' om originalet kommer fran en konkurrent.\n"
        "Formulera konkurrentcase som: 'Vill du bygga en liknande losning?', 'Sa kan en losning anpassas efter din bil'.\n"
        "Anvand inte specifika produktnamn om de inte ar godkanda: " + ", ".join(APPROVED_PRODUCTS) + ".\n"
        "Anvand inte konkurrentens namn, handle eller varumarke i caption eller bildprompt.\n\n"
        "COPY-REGLER:\n"
        "Skriv som FAIV: premium, konkret, tryggt, svenskt och praktiskt.\n"
        "Undvik generisk AI-saljcopy och overdrivna emojis.\n"
        "Hooks max tva rader. Captions max 120 ord.\n"
        "Valj CTA bland: " + ", ".join(ALLOWED_CTAS) + ".\n\n"
        "AI-BILDPROMPT-REGLER:\n"
        "fallback_image_prompt ska vara extremt detaljerad, minst 200 tecken, helst 300+.\n"
        "Prompten ska innehalla: exakt motiv, fordonstyp, miljo, ljusattning, kameravinkel, "
        "bildkomposition, fargton, premiumkansla, svensk/skandinavisk kontext, "
        "vad bilden ska lamna plats for (t.ex. text-overlay), vad som inte far finnas "
        "(logotyper, text, registreringsnummer, deformerade lampor), "
        "bildformat (4:5 for feed/carousel, 9:16 for story/reel).\n"
        "Prompten ska vara konkret nog att anvandas direkt i en bildgenerator.\n"
        "Prompten ska inte namnda konkurrentens handle eller varumarke.\n"
        "Prompten ska inte be om en exakt kopia av originalbilden.\n\n"
        "OVERLAY/SKIDE-REGLER:\n"
        "overlay_text: kort text som ska ligga pa bilden (inte i caption).\n"
        "carousel_structure: om format ar carousel, skapa slide-objekt med purpose, overlay_text, image_need per slide.\n\n"
        "Returnera bara JSON enligt schemat.\n\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def parse_proposal_response(raw_response: str) -> list[dict]:
    rows = parse_json_payload(raw_response)
    proposals: list[dict] = []

    for row in rows:
        missing = REQUIRED_PROPOSAL_FIELDS - row.keys()
        if missing:
            missing_fields = ", ".join(sorted(missing))
            raise ValueError(f"Proposal output missing required fields: {missing_fields}")
        proposals.append(row)
    return proposals


def _validate_copy(caption: str) -> str:
    lowered = caption.lower()
    for phrase in FORBIDDEN_COPY_PHRASES:
        if phrase in lowered:
            return "needs_edit"
    return ""


def _determine_status(
    proposal_data: dict,
    faiv_content_category: str,
    asset_confidence: float,
    asset_confidence_threshold: float,
) -> str:
    category_lower = faiv_content_category.lower()

    if category_lower == "kundbyggen" and asset_confidence < asset_confidence_threshold:
        return "needs_photo"

    if asset_confidence >= asset_confidence_threshold:
        return "ready_to_design"

    prompt = (proposal_data.get("fallback_image_prompt") or "").strip()
    if len(prompt) >= MIN_AI_PROMPT_LENGTH:
        return "needs_ai_image"

    return "needs_edit"


def generate_proposals(
    candidates: Iterable[CandidatePost],
    *,
    model: str,
    fallback_model: str,
    client: OpenRouterClient,
    asset_confidence_threshold: float = 0.65,
) -> list[Proposal]:
    candidate_list = list(candidates)
    if not candidate_list:
        return []
    raw_response = client.structured_chat(
        model=model or fallback_model,
        system_prompt=(
            "Du skriver svensk social copy for FAIV och returnerar strikt JSON. "
            "faiv_content_category ar alltid en av de fyra innehallskategorierna. "
            "service_area ar alltid ett tjanteomrade. "
            "Du lurar aldrig pa att FAIV har gjort ett jobb som kommer fran en konkurrent."
        ),
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

        faiv_cat = row.get("faiv_content_category", source_candidate.faiv_content_category)
        service_area = row.get("service_area", source_candidate.service_area)
        carousel = row.get("carousel_structure", [])
        if not isinstance(carousel, list):
            carousel = []

        proposal = Proposal(
            source_candidate=source_candidate,
            hook=row["hook"],
            caption=row["caption"],
            cta=row["cta"],
            format=row["format"],
            image_brief=row["image_brief"],
            recommended_asset_folder=row["recommended_asset_folder"],
            fallback_image_prompt=row["fallback_image_prompt"],
            why_selected=row["why_selected"],
            faiv_content_category=faiv_cat,
            service_area=service_area,
            status="needs_edit",
            overlay_text=row.get("overlay_text", ""),
            carousel_structure=carousel,
            image_plan=row.get("image_plan", ""),
            asset_match_confidence=0.0,
            selected_asset="",
            production_note="",
            originality_risk=source_candidate.originality_risk,
            drive_folder_url="",
            dedupe_key=source_candidate.source_post.post_url,
        )

        copy_status = _validate_copy(proposal.caption)
        if copy_status:
            proposal.status = copy_status
        else:
            proposal.status = _determine_status(
                row,
                faiv_cat,
                0.0,
                asset_confidence_threshold,
            )

        proposals.append(proposal)

    return proposals
