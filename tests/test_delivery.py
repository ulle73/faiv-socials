from src.deliver import build_status_email, should_create_document
from src.models import RunSummary


def test_should_create_document_only_when_three_or_more_proposals_exist():
    assert should_create_document(0) is False
    assert should_create_document(2) is False
    assert should_create_document(3) is True


def test_build_status_email_includes_doc_link_when_present():
    summary = RunSummary(
        run_date="2026-06-23",
        active_batch="A",
        collected_count=29,
        candidate_count=8,
        proposal_count=5,
        blocked_accounts=["example_blocked"],
        warnings=[],
        errors=[],
        doc_url="https://docs.google.com/document/d/example/edit",
    )

    subject, body = build_status_email(summary)

    assert "FAIV sociala medier" in subject
    assert "Dagens doc" in body
    assert summary.doc_url in body
