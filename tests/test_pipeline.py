from src.models import SourceAccount
from src.pipeline import merge_updated_source_rows


def test_merge_updated_source_rows_applies_status_and_last_fetched_from_collection_results():
    source_rows = [
        {
            "handle": "ekstralys.no",
            "lookup_term": "@ekstralys.no",
            "company_name": "Ekstralys.no",
            "status": "ok",
            "last_fetched": "",
            "active": "yes",
        }
    ]
    updated_sources = [
        SourceAccount(
            priority=1,
            tier="1",
            company_name="Ekstralys.no",
            raw_lookup="@ekstralys.no",
            lookup_term="@ekstralys.no",
            country="Norge",
            faiv_categories=["Förvandlingar"],
            frequency="Dagligen",
            comment="",
            handle="ekstralys.no",
            active=True,
            batch="A",
            last_fetched="2026-06-23",
            status="tom",
        )
    ]

    merged = merge_updated_source_rows(source_rows, updated_sources)

    assert merged[0]["status"] == "tom"
    assert merged[0]["last_fetched"] == "2026-06-23"
