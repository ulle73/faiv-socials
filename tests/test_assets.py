from src.assets import match_asset_folder
from src.models import CandidatePost, CollectedPost, Proposal


def _proposal(recommended_asset_folder: str, category: str) -> Proposal:
    source_post = CollectedPost(
        source_handle="ekstralys.no",
        post_url="https://example.com/post-1",
        published_at="2026-06-23T07:00:00+02:00",
        caption="Post 1",
        post_type="image",
        media_urls=["https://example.com/a.jpg"],
        hook_signal="Post 1",
        batch_date="2026-06-23",
    )
    candidate = CandidatePost(
        source_post=source_post,
        faiv_fit=28,
        lead_potential=20,
        hook_strength=18,
        visual_transferability=14,
        novelty=8,
        total_score=88,
        faiv_category=category,
        why_it_works="Tydligt värde.",
        originality_risk="låg",
    )
    return Proposal(
        source_candidate=candidate,
        hook="Extraljus behöver inte se eftermonterat ut.",
        caption="Kort svensk caption.",
        cta="Skicka DM för offert.",
        format="karusell",
        image_brief="Visa före/efter.",
        recommended_asset_folder=recommended_asset_folder,
        fallback_image_prompt="Fotorealistisk verkstadsbild.",
        why_selected="Stark nordisk relevans.",
    )


def test_match_asset_folder_uses_requested_folder_and_flags_low_inventory():
    proposal = _proposal("grillkit", "Förvandlingar")
    asset_rows = [
        {"folder": "grillkit", "file_name": "grillkit-volvo-fh.jpg", "category": "grillkit"},
        {"folder": "grillkit", "file_name": "grillkit-transit.jpg", "category": "grillkit"},
    ]

    match = match_asset_folder(proposal, asset_rows)

    assert match.folder == "grillkit"
    assert match.image_count == 2
    assert match.confidence == "low"
    assert match.use_ai_prompt is True


def test_match_asset_folder_falls_back_to_category_mapping():
    proposal = _proposal("", "Bakom bygget")
    asset_rows = [
        {"folder": "verkstad", "file_name": "verkstad-1.jpg", "category": "verkstad"},
        {"folder": "verkstad", "file_name": "verkstad-2.jpg", "category": "verkstad"},
        {"folder": "verkstad", "file_name": "verkstad-3.jpg", "category": "verkstad"},
    ]

    match = match_asset_folder(proposal, asset_rows)

    assert match.folder == "verkstad"
    assert match.image_count == 3
    assert match.confidence == "medium"
    assert match.use_ai_prompt is False
