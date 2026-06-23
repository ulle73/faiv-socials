import pytest

from src.analyze import parse_analysis_response
from src.models import CollectedPost
from src.propose import generate_proposals, parse_proposal_response


def test_parse_analysis_response_filters_by_min_score_and_accepts_markdown_wrapped_json():
    raw_response = """```json
[
  {
    "url": "https://example.com/post-1",
    "faiv_fit": 26,
    "lead_potential": 20,
    "hook_strength": 17,
    "visual_transferability": 12,
    "novelty": 8,
    "total": 83,
    "faiv_category": "Förvandlingar",
    "why_it_works": "Tydlig före/efter och stark produktvinkel.",
    "originality_risk": "låg"
  },
  {
    "url": "https://example.com/post-2",
    "faiv_fit": 12,
    "lead_potential": 10,
    "hook_strength": 8,
    "visual_transferability": 6,
    "novelty": 4,
    "total": 40,
    "faiv_category": "Bakom bygget",
    "why_it_works": "För svag för FAIV.",
    "originality_risk": "medel"
  }
]
```"""
    post_lookup = {
        "https://example.com/post-1": CollectedPost(
            source_handle="ekstralys.no",
            post_url="https://example.com/post-1",
            published_at="2026-06-23T07:00:00+02:00",
            caption="Post 1",
            post_type="image",
            media_urls=["https://example.com/a.jpg"],
            hook_signal="Post 1",
            batch_date="2026-06-23",
        ),
        "https://example.com/post-2": CollectedPost(
            source_handle="ekstralys.no",
            post_url="https://example.com/post-2",
            published_at="2026-06-23T07:00:00+02:00",
            caption="Post 2",
            post_type="image",
            media_urls=["https://example.com/b.jpg"],
            hook_signal="Post 2",
            batch_date="2026-06-23",
        ),
    }

    candidates = parse_analysis_response(raw_response, post_lookup, min_score=60)

    assert len(candidates) == 1
    assert candidates[0].total_score == 83
    assert candidates[0].faiv_category == "Förvandlingar"
    assert candidates[0].source_post.post_url == "https://example.com/post-1"


def test_parse_proposal_response_requires_all_required_fields():
    incomplete = """
    [
      {
        "source_url": "https://example.com/post-1",
        "hook": "Extraljus behöver inte se eftermonterat ut."
      }
    ]
    """

    with pytest.raises(ValueError):
        parse_proposal_response(incomplete)


def test_generate_proposals_short_circuits_when_no_candidates_exist():
    class DummyClient:
        def __init__(self) -> None:
            self.called = False

        def structured_chat(self, **kwargs):  # noqa: ANN003
            self.called = True
            return "[]"

    client = DummyClient()

    proposals = generate_proposals([], model="model", fallback_model="fallback", client=client)

    assert proposals == []
    assert client.called is False
