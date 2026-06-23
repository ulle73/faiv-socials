from __future__ import annotations

import re
from typing import Iterable

from src.models import SourceAccount


ACCOUNT_PATTERN = re.compile(r"@([A-Za-z0-9._]+)")
UNVERIFIED_MARKERS = ("verifiera handle", "sök via")
BATCH_SEQUENCE = ("A", "B", "C")


def parse_watchlist_markdown(markdown: str) -> list[SourceAccount]:
    accounts: list[SourceAccount] = []
    in_table = False

    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if line.startswith("| Prio | Tier | Företag / konto |"):
            in_table = True
            continue

        if not in_table:
            continue

        if not line.startswith("|"):
            break

        if line.startswith("|---"):
            continue

        columns = [column.strip() for column in line.strip("|").split("|")]
        if len(columns) != 8:
            continue

        priority, tier, company_name, lookup_cell, country, categories, frequency, comment = columns
        normalized_lookup = lookup_cell.strip()
        handle_match = ACCOUNT_PATTERN.search(normalized_lookup)
        handle = handle_match.group(1) if handle_match else None
        lowered = normalized_lookup.lower()
        active = not any(marker in lowered for marker in UNVERIFIED_MARKERS)
        status = "ok" if active else "needs_handle"

        if handle is None and active and normalized_lookup:
            compact = normalized_lookup.replace("https://www.instagram.com/", "").strip("/")
            if " " not in compact and compact.lower() not in {"okänd", "none"}:
                handle = compact

        accounts.append(
            SourceAccount(
                priority=_to_int(priority),
                tier=tier,
                company_name=company_name,
                raw_lookup=lookup_cell,
                lookup_term=normalized_lookup,
                country=country,
                faiv_categories=[item.strip() for item in categories.split(",") if item.strip()],
                frequency=frequency,
                comment=comment,
                handle=handle,
                active=active and handle is not None,
                status=status if handle is None else "ok",
            )
        )

    return accounts


def assign_batches(accounts: Iterable[SourceAccount]) -> list[SourceAccount]:
    assigned = list(accounts)
    active_accounts = [account for account in assigned if account.active]
    for index, account in enumerate(active_accounts):
        account.batch = BATCH_SEQUENCE[index % len(BATCH_SEQUENCE)]
    for account in assigned:
        if not account.active:
            account.batch = ""
    return assigned


def next_batch(current_batch: str) -> str:
    current = (current_batch or "").strip().upper()
    if current not in BATCH_SEQUENCE:
        return "A"
    next_index = (BATCH_SEQUENCE.index(current) + 1) % len(BATCH_SEQUENCE)
    return BATCH_SEQUENCE[next_index]


def source_account_to_row(account: SourceAccount) -> dict[str, str]:
    return {
        "handle": account.handle or "",
        "lookup_term": account.lookup_term,
        "company_name": account.company_name,
        "priority": str(account.priority),
        "tier": account.tier,
        "country": account.country,
        "category_fit": ", ".join(account.faiv_categories),
        "frequency": account.frequency,
        "active": "yes" if account.active else "no",
        "batch": account.batch,
        "last_fetched": account.last_fetched,
        "status": account.status,
        "comment": account.comment,
    }


def _to_int(value: str) -> int:
    try:
        return int(value.strip())
    except ValueError:
        return 999
