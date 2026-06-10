# FHIR verification step: the "prove it works" part
#
# Takes one created test patient ID (handed over from loader.py via cli.py)
# and pulls their record back from the HealthEx FHIR server with the
# $everything API, then prints it: both a short summary and the full bundle
#
# Reference: https://docs.healthex.io/fhir-server


from __future__ import annotations
from typing import Any, Optional
from .client import HealthExClient, HealthExAPIError


def _everything_path(patient_id: str) -> str:
    return f"/FHIR/R4/Person/{patient_id}/$everything"  # FHIR $everything API


# Fetch test patient FHIR bundle
def fetch_patient_everything(
    client: HealthExClient,
    patient_id: str,
    *,
    count: Optional[int] = 30,
    resource_types: Optional[list[str]] = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if count is not None:
        params["_count"] = count
    if resource_types:
        params["_type"] = ",".join(resource_types)

    try:
        return client.get(_everything_path(patient_id), params=params) or {}
    except HealthExAPIError as exc:
        if exc.status == 403:
            raise HealthExAPIError(
                f"FHIR access forbidden for {patient_id} (403). ",
                status=403,
                body=exc.body,
            ) from exc
        raise


# Pull a few fiels from bundle to print out
def summarize_for_display(bundle: dict[str, Any]) -> dict[str, Any]:
    entries = bundle.get("entry", [])
    by_type: dict[str, int] = {}
    name = None
    conditions: list[str] = []

    for entry in entries:
        res = entry.get("resource", {})
        rt = res.get("resourceType")
        if not rt:
            continue
        by_type[rt] = by_type.get(rt, 0) + 1

        if rt in ("Person", "Patient") and name is None:
            n = (res.get("name") or [{}])[0]
            given = " ".join(n.get("given", []) or [])
            name = f"{given} {n.get('family', '')}".strip() or None
        if rt == "Condition":
            code = res.get("code", {})
            txt = code.get("text") or (code.get("coding") or [{}])[0].get("display")
            if txt:
                conditions.append(txt)

    return {
        "name": name,
        "total_resources": len(entries),
        "resource_counts": by_type,
        "sample_conditions": conditions[:5],
    }


# Summarize patient: Returns both the parsed summary and the full bundle
# so the caller can print the complete FHIR response
def verify_patient(client: HealthExClient, patient_id: str) -> dict[str, Any]:
    bundle = fetch_patient_everything(client, patient_id)
    summary = summarize_for_display(bundle)
    summary["bundle"] = bundle
    return summary


# Pretty-print the entire FHIR bundle as formatted JSON
def print_full_bundle(bundle: dict[str, Any]) -> None:
    import json

    print(json.dumps(bundle, indent=2, ensure_ascii=False))
