from src.config import (
    FAIV_CONTENT_CATEGORIES,
    SERVICE_AREAS,
    PROPOSAL_STATUSES,
    APPROVED_PRODUCTS,
    ALLOWED_CTAS,
    FORBIDDEN_COPY_PHRASES,
    ASSET_CONFIDENCE_THRESHOLD,
    MIN_AI_PROMPT_LENGTH,
    DEFAULT_FEED_FORMAT,
    DEFAULT_STORY_FORMAT,
)
from src.models import Proposal, CandidatePost, CollectedPost, RunSummary
from src.propose import _validate_copy, _determine_status, build_proposal_prompt
from src.analyze import build_analysis_prompt
from src.deliver import _render_document_body, _render_post_md, _proposal_to_dict, _render_source_json
import json


def _make_candidate(**overrides):
    defaults = dict(
        source_post=CollectedPost(
            source_handle="test",
            post_url="https://instagram.com/p/test/",
            published_at="2026-01-01T00:00:00Z",
            caption="test caption",
            post_type="Image",
            media_urls=[],
            hook_signal="test",
            batch_date="2026-01-01",
        ),
        faiv_fit=80,
        lead_potential=70,
        hook_strength=75,
        visual_transferability=80,
        novelty=65,
        total_score=290,
        faiv_content_category="Forvandlingar",
        service_area="extrabelysning",
        why_it_works="strong visual",
        originality_risk="low",
    )
    defaults.update(overrides)
    return CandidatePost(**defaults)


def _make_proposal(**overrides):
    candidate = overrides.pop("source_candidate", None) or _make_candidate()
    defaults = dict(
        source_candidate=candidate,
        hook="Diskret extraljus gor stor skillnad",
        caption="Ratt ljus gor stor skillnad nar du kor morgon och kvall.",
        cta="Hor av dig till oss",
        format="carousel",
        image_brief="Fore/efter front",
        recommended_asset_folder="extrabelysning",
        fallback_image_prompt="",
        why_selected="Strong visual transferability",
        faiv_content_category=candidate.faiv_content_category,
        service_area=candidate.service_area,
        status="needs_edit",
        overlay_text="Ratt ljus",
        carousel_structure=[],
        image_plan="",
        asset_match_confidence=0.0,
        selected_asset="",
        production_note="",
        originality_risk="low",
        drive_folder_url="",
        dedupe_key="https://instagram.com/p/test/",
    )
    defaults.update(overrides)
    return Proposal(**defaults)


SERVICE_AREA_VALUES = ["servicebil", "extrabelysning", "arbetsljus", "grillkit", "verkstad"]


def test_faiv_content_category_never_contains_service_area():
    for sa in SERVICE_AREA_VALUES:
        assert sa not in [c.lower() for c in FAIV_CONTENT_CATEGORIES]


def test_faiv_content_category_always_valid():
    valid = [c.lower() for c in FAIV_CONTENT_CATEGORIES]
    for cat in FAIV_CONTENT_CATEGORIES:
        assert cat.lower() in valid


def test_service_area_set_separately():
    proposal = _make_proposal()
    assert proposal.service_area == "extrabelysning"
    assert proposal.faiv_content_category == "Forvandlingar"


def test_forbidden_copy_phrases_detected():
    for phrase in ["vi monterade", "vi byggde", "vi utrustade"]:
        status = _validate_copy("Dette ar en caption dar " + phrase + " extrabelysningen.")
        assert status == "needs_edit"


def test_clean_copy_passes():
    status = _validate_copy("Ratt ljus gor stor skillnad i vardagen.")
    assert status == ""


def test_kundbyggen_without_asset_becomes_needs_photo():
    status = _determine_status({}, "Kundbyggen", 0.0, 0.65)
    assert status == "needs_photo"


def test_high_confidence_becomes_ready_to_design():
    status = _determine_status({}, "Forvandlingar", 0.8, 0.65)
    assert status == "ready_to_design"


def test_low_confidence_with_long_prompt_becomes_needs_ai_image():
    long_prompt = "x" * 250
    status = _determine_status({"fallback_image_prompt": long_prompt}, "Forvandlingar", 0.2, 0.65)
    assert status == "needs_ai_image"


def test_ready_to_post_requires_asset():
    proposal = _make_proposal(asset_match_confidence=0.0, selected_asset="")
    assert proposal.status != "ready_to_post"


def test_proposal_always_has_required_fields():
    proposal = _make_proposal()
    for field in ["hook", "caption", "cta", "format", "image_brief", "status"]:
        assert hasattr(proposal, field)
        assert getattr(proposal, field) is not None


def test_min_ai_prompt_length_is_200():
    assert MIN_AI_PROMPT_LENGTH == 200


def test_asset_confidence_threshold_is_065():
    assert ASSET_CONFIDENCE_THRESHOLD == 0.65


def test_default_feed_format_is_4_5():
    assert DEFAULT_FEED_FORMAT == "4:5"


def test_default_story_format_is_9_16():
    assert DEFAULT_STORY_FORMAT == "9:16"


def test_all_statuses_defined():
    expected = {"ready_to_post", "ready_to_design", "needs_photo", "needs_ai_image", "needs_edit", "discarded"}
    assert set(PROPOSAL_STATUSES) == expected


def test_google_doc_grouped_by_status():
    summary = RunSummary(
        run_date="2026-06-24",
        active_batch="A",
        collected_count=29,
        candidate_count=12,
        proposal_count=3,
        blocked_accounts=[],
        warnings=[],
        errors=[],
    )
    proposals = [
        _make_proposal(status="ready_to_post", faiv_content_category="Forvandlingar"),
        _make_proposal(status="needs_photo", faiv_content_category="Kundbyggen"),
        _make_proposal(status="needs_ai_image", faiv_content_category="Ratt val"),
    ]
    body = _render_document_body(proposals, summary)
    assert "Klara att publicera" in body
    assert "Behover foto" in body
    assert "Behover AI-bild" in body


def test_post_md_contains_status_and_category():
    proposal = _make_proposal(status="needs_ai_image")
    md = _render_post_md(proposal)
    assert "Status:" in md
    assert "needs_ai_image" in md
    assert "FAIV-kategori:" in md
    assert "Forvandlingar" in md
    assert "Tjanteomrade:" in md
    assert "extrabelysning" in md


def test_proposal_json_contains_full_object():
    proposal = _make_proposal(status="ready_to_design")
    d = _proposal_to_dict(proposal)
    assert "hook" in d
    assert "caption" in d
    assert "faiv_content_category" in d
    assert "service_area" in d
    assert "status" in d
    assert d["status"] == "ready_to_design"


def test_source_json_contains_dedupe_key():
    proposal = _make_proposal()
    raw = _render_source_json(proposal)
    data = json.loads(raw)
    assert "dedupe_key" in data
    assert data["dedupe_key"] == "https://instagram.com/p/test/"
    assert "original_post_url" in data


def test_ai_prompt_not_shorter_than_200_when_needs_ai_image():
    status = _determine_status({"fallback_image_prompt": "x" * 100}, "Forvandlingar", 0.2, 0.65)
    assert status != "needs_ai_image"


def test_proposal_prompt_forbids_competitor_handle():
    candidate = _make_candidate()
    prompt = build_proposal_prompt([candidate])
    assert "konkurrent" in prompt.lower() or "varumarke" in prompt.lower()


def test_analysis_prompt_separates_category_and_service_area():
    post = CollectedPost(
        source_handle="test",
        post_url="https://instagram.com/p/test/",
        published_at="2026-01-01T00:00:00Z",
        caption="test",
        post_type="Image",
        media_urls=[],
        hook_signal="test",
        batch_date="2026-01-01",
    )
    prompt = build_analysis_prompt([post])
    assert "faiv_content_category" in prompt
    assert "service_area" in prompt
    assert "Forvandlingar" in prompt or "forvandlingar" in prompt.lower()
    assert "extrabelysning" in prompt