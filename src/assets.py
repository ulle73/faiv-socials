from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from src.models import AssetMatch, Proposal


FAIV_CATEGORY_FALLBACKS = {
    "Förvandlingar": "kundbyggen",
    "Kundbyggen": "kundbyggen",
    "Rätt val": "extrabelysning",
    "Bakom bygget": "verkstad",
}


def match_asset_folder(proposal: Proposal, asset_rows: Iterable[dict[str, str]]) -> AssetMatch:
    by_folder: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in asset_rows:
        folder = (row.get("folder") or "").strip()
        if folder:
            by_folder[folder].append(row)

    requested_folder = (proposal.recommended_asset_folder or "").strip()
    fallback_folder = FAIV_CATEGORY_FALLBACKS.get(proposal.source_candidate.faiv_content_category, "verkstad")
    chosen_folder = requested_folder if requested_folder in by_folder else fallback_folder
    image_count = len(by_folder.get(chosen_folder, []))

    if image_count >= 8:
        confidence = "high"
    elif image_count >= 3:
        confidence = "medium"
    else:
        confidence = "low"

    return AssetMatch(
        folder=chosen_folder,
        image_count=image_count,
        confidence=confidence,
        use_ai_prompt=image_count < 3,
    )


def build_asset_library_rows_from_drive(drive_files: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for item in drive_files:
        folder = item.get("folder", "")
        file_name = item.get("name", "")
        rows.append(
            {
                "folder": folder,
                "file_name": file_name,
                "category": folder,
                "keywords": _keywords_from_filename(file_name),
            }
        )
    return rows


def _keywords_from_filename(file_name: str) -> str:
    clean = file_name.rsplit(".", 1)[0]
    return ", ".join(part for part in clean.replace("_", "-").split("-") if part)
