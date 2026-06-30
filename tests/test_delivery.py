from src.deliver import DeliveryService, should_create_document
from src.models import CandidatePost, CollectedPost, Proposal, RunSummary


def test_should_create_document_only_when_at_least_one_proposal_exists():
    assert should_create_document(0) is False
    assert should_create_document(1) is True
    assert should_create_document(5) is True


def _make_proposal() -> Proposal:
    candidate = CandidatePost(
        source_post=CollectedPost(
            source_handle="testkonto",
            post_url="https://instagram.com/p/test/",
            published_at="2026-06-30T05:00:00Z",
            caption="Original caption",
            post_type="Image",
            media_urls=[],
            hook_signal="test",
            batch_date="2026-06-30",
        ),
        faiv_fit=80,
        lead_potential=70,
        hook_strength=75,
        visual_transferability=80,
        novelty=65,
        total_score=290,
        faiv_content_category="Forvandlingar",
        service_area="extrabelysning",
        why_it_works="Starkt fore-efter-varde.",
        originality_risk="low",
    )
    return Proposal(
        source_candidate=candidate,
        hook="Sa far du ordning i servicebilen",
        caption="En tydlig och konkret caption.",
        cta="Skicka ett DM",
        format="Carousel, 4:5",
        image_brief="Visa en ren och ljus servicebil.",
        recommended_asset_folder="servicebilar",
        fallback_image_prompt="Detailed prompt",
        why_selected="Relevant for FAIVs kunder.",
        faiv_content_category="Forvandlingar",
        service_area="servicebilar",
        status="ready_to_design",
        drive_folder_url="https://drive.google.com/folder/test",
    )


def _make_summary(proposal_count: int) -> RunSummary:
    return RunSummary(
        run_date="2026-06-30",
        active_batch="A",
        collected_count=12,
        candidate_count=5,
        proposal_count=proposal_count,
        blocked_accounts=[],
        warnings=[],
        errors=[],
        source_count=8,
        doc_url="https://docs.google.com/document/d/test/edit",
    )


class _FakeSender:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def send_message(self, content: str) -> None:
        self.messages.append(content)


def test_deliver_to_discord_sends_no_proposal_status_when_empty():
    delivery = DeliveryService(None, None)
    sender = _FakeSender()

    sent = delivery.deliver_to_discord([], _make_summary(0), sender)

    assert len(sent) == 1
    assert len(sender.messages) == 1
    assert "Inga postpaket" in sender.messages[0]


def test_deliver_to_discord_sends_each_proposal_and_completion_status():
    delivery = DeliveryService(None, None)
    sender = _FakeSender()
    proposals = [_make_proposal()]

    sent = delivery.deliver_to_discord(proposals, _make_summary(1), sender)

    assert len(sent) == 2
    assert len(sender.messages) == 2
    assert "Forslag 1" in sender.messages[0]
    assert "Drive" in sender.messages[0]
    assert "Korning klar" in sender.messages[1]
