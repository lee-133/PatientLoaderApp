# Flatten bundle into a compact summary
# Iterate each bundle once and produce a small PatientSummary
# (name, age, gender, language, state, complexity tier, active conditions)
# Bundles are ~7MB each, so we parse once into these summaries and let
# filters.py operate on them: never re-reading the raw bundles


from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

from .tiers import load_index, tier_for_filename


@dataclass
class PatientSummary:
    # Compact filter-friendly view of patient bundle
    patient_id: Optional[str]
    first_name: str
    last_name: str
    gender: Optional[str]
    birth_date: Optional[str]
    age: Optional[int]
    state: Optional[str]
    language: Optional[str]  # e.g. "en", "es"
    tier: Optional[str]  # key from tiers.TIERS, or None if unmatched

    active_conditions: list[str] = field(default_factory=list)
    active_condition_count: int = 0

    source_path: Optional[str] = None

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


# helpers
def _coding(concept: dict[str, Any]) -> dict[str, Any]:
    codings = concept.get("coding") or [{}]
    return codings[0] if codings else {}


def _concept_text(concept: dict[str, Any]) -> str:
    return concept.get("text") or _coding(concept).get("display", "") or ""


def _calc_age(
    birth_date: Optional[str], *, today: Optional[date] = None
) -> Optional[int]:
    if not birth_date:
        return None
    today = today or date.today()
    try:
        bd = datetime.strptime(birth_date[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
    return today.year - bd.year - ((today.month, today.day) < (bd.month, bd.day))


def _is_active(condition: dict[str, Any]) -> bool:
    return _coding(condition.get("clinicalStatus", {})).get("code") == "active"


# Main entry points
def summarize_bundle(
    bundle: dict[str, Any],
    *,
    source_path: str | Path | None = None,
    tier: Optional[str] = None,
    today: Optional[date] = None,
) -> PatientSummary:
    # Return a PatientSummary

    resources_by_type: dict[str, list[dict[str, Any]]] = {}
    for entry in bundle.get("entry", []):
        res = entry.get("resource", {})
        rt = res.get("resourceType")
        if rt:
            resources_by_type.setdefault(rt, []).append(res)

    patients = resources_by_type.get("Patient", [])
    patient = patients[0] if patients else {}

    name = (patient.get("name") or [{}])[0]
    given = name.get("given") or []
    first = given[0] if given else ""
    last = name.get("family", "") or ""

    birth_date = patient.get("birthDate")
    state = (patient.get("address") or [{}])[0].get("state")

    language = None
    comms = patient.get("communication") or []
    if comms:
        lang_code = _coding(comms[0].get("language", {})).get("code")
        if lang_code:
            language = lang_code.split("-")[0].lower()  # "en-us" -> "en"

    active_conditions = [
        _concept_text(c.get("code", {}))
        for c in resources_by_type.get("Condition", [])
        if _is_active(c)
    ]

    return PatientSummary(
        patient_id=patient.get("id"),
        first_name=first,
        last_name=last,
        gender=patient.get("gender"),
        birth_date=birth_date,
        age=_calc_age(birth_date, today=today),
        state=state,
        language=language,
        tier=tier,
        active_conditions=active_conditions,
        active_condition_count=len(active_conditions),
        source_path=str(source_path) if source_path else None,
    )


# Load a single bundle JSON file and summarize it
def summarize_file(
    path: str | Path,
    *,
    file_to_tier: Optional[dict[str, str]] = None,
    today: Optional[date] = None,
) -> PatientSummary:
    path = Path(path)
    with path.open() as fh:
        bundle = json.load(fh)
    tier = tier_for_filename(path.name, file_to_tier) if file_to_tier else None
    return summarize_bundle(bundle, source_path=path, tier=tier, today=today)


# Summarize every bundle file in directory
def summarize_dir(
    directory: str | Path,
    *,
    pattern: str = "*.json",
    index_path: str | Path | None = None,
    today: Optional[date] = None,
) -> list[PatientSummary]:
    directory = Path(directory)
    if index_path is None:
        candidate = directory / "index.html"
        index_path = candidate if candidate.exists() else None
    file_to_tier = load_index(index_path) if index_path else {}

    summaries: list[PatientSummary] = []
    for path in sorted(directory.glob(pattern)):
        try:
            summaries.append(
                summarize_file(path, file_to_tier=file_to_tier, today=today)
            )
        except (json.JSONDecodeError, OSError) as exc:
            print(f"warning: skipping {path.name}: {exc}")
    return summaries
