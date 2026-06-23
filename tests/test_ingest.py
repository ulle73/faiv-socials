from src.ingest import select_accounts_for_collection
from src.models import SourceAccount


def test_select_accounts_for_collection_uses_batch_for_active_accounts():
    accounts = [
        SourceAccount(
            priority=1,
            tier="1",
            company_name="One",
            raw_lookup="@one",
            lookup_term="@one",
            country="SE",
            faiv_categories=["Kundbyggen"],
            frequency="Dagligen",
            comment="",
            handle="one",
            active=True,
            batch="A",
        ),
        SourceAccount(
            priority=1,
            tier="1",
            company_name="Two",
            raw_lookup="@two",
            lookup_term="@two",
            country="SE",
            faiv_categories=["Kundbyggen"],
            frequency="Dagligen",
            comment="",
            handle="two",
            active=True,
            batch="B",
        ),
        SourceAccount(
            priority=1,
            tier="1",
            company_name="Three",
            raw_lookup="@three",
            lookup_term="@three",
            country="SE",
            faiv_categories=["Kundbyggen"],
            frequency="Dagligen",
            comment="",
            handle="three",
            active=False,
            batch="A",
        ),
    ]

    result = select_accounts_for_collection(accounts, batch="A", handles=None)

    assert [account.handle for account in result] == ["one"]


def test_select_accounts_for_collection_prefers_explicit_handles():
    accounts = [
        SourceAccount(
            priority=1,
            tier="1",
            company_name="One",
            raw_lookup="@one",
            lookup_term="@one",
            country="SE",
            faiv_categories=["Kundbyggen"],
            frequency="Dagligen",
            comment="",
            handle="one",
            active=True,
            batch="A",
        ),
        SourceAccount(
            priority=1,
            tier="1",
            company_name="Two",
            raw_lookup="@two",
            lookup_term="@two",
            country="SE",
            faiv_categories=["Kundbyggen"],
            frequency="Dagligen",
            comment="",
            handle="two",
            active=True,
            batch="B",
        ),
    ]

    result = select_accounts_for_collection(accounts, batch="A", handles=["two"])

    assert [account.handle for account in result] == ["two"]


def test_select_accounts_for_collection_adds_explicit_handles_missing_from_watchlist():
    accounts = [
        SourceAccount(
            priority=1,
            tier="1",
            company_name="One",
            raw_lookup="@one",
            lookup_term="@one",
            country="SE",
            faiv_categories=["Kundbyggen"],
            frequency="Dagligen",
            comment="",
            handle="one",
            active=True,
            batch="A",
        ),
    ]

    result = select_accounts_for_collection(accounts, batch="A", handles=["outside_handle"])

    assert [account.handle for account in result] == ["outside_handle"]
    assert result[0].active is True
    assert result[0].lookup_term == "@outside_handle"
