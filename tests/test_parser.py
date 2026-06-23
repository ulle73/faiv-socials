from pathlib import Path

from src.watchlist import assign_batches, next_batch, parse_watchlist_markdown


def test_parse_watchlist_extracts_accounts_and_disables_unverified_handles():
    markdown = """
| Prio | Tier | Företag / konto | Handle / sökterm | Land | Bäst för FAIV-kategorier | Frekvens | Kommentar |
|---:|---|---|---|---|---|---|---|
| 1 | 1 | Ekstralys.no | @ekstralys.no | Norge | Rätt val, Bakom bygget | Dagligen | Direkt relevant. |
| 2 | 1 | Holman Vehicle Upfitting | Verifiera handle / sökterm | USA | Kundbyggen | Dagligen | Behöver verifieras. |
| 3 | 1 | Lumen Grillkits | Sök via Ekstralys/Lumen | Norge | Förvandlingar, Rätt val | Dagligen | Viktigt produktområde. |
"""

    accounts = parse_watchlist_markdown(markdown)

    assert len(accounts) == 3
    assert accounts[0].handle == "ekstralys.no"
    assert accounts[0].active is True
    assert accounts[0].status == "ok"
    assert accounts[1].handle is None
    assert accounts[1].active is False
    assert accounts[1].status == "needs_handle"
    assert accounts[2].lookup_term == "Sök via Ekstralys/Lumen"


def test_assign_batches_round_robins_collectable_sources_from_repository_watchlist():
    watchlist = Path("faiv-sociala-medier-watchlist.md").read_text(encoding="utf-8")

    assigned = assign_batches(parse_watchlist_markdown(watchlist))
    active = [account for account in assigned if account.active]
    counts = {
        batch: sum(1 for account in active if account.batch == batch)
        for batch in ("A", "B", "C")
    }

    assert all(count > 0 for count in counts.values())
    assert max(counts.values()) - min(counts.values()) <= 1


def test_next_batch_rotates_in_sequence():
    assert next_batch("A") == "B"
    assert next_batch("B") == "C"
    assert next_batch("C") == "A"
    assert next_batch("unknown") == "A"
