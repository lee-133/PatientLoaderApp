# Upload workflow: filtered patients -> test patients -> project -> consent
# It knows about patients and projects, and it calls client.py for every HTTP request
# Endpoint paths and payload shapes are defined as constants / small builder
# functions at the top, so if a field name or path differs from the docs it's
# a one-line change here rather than buried in the flow


from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Optional
from .client import HealthExClient, HealthExAPIError
from .auth import patient_token, AuthError
from .extract import PatientSummary


# API endpoint paths
def _create_test_patient_path(org_id: str) -> str:
    return f"/v1/organizations/{org_id}/test-patients"


def _add_patients_path(project_id: str) -> str:
    return f"/v1/projects/{project_id}/patients"


def _consent_path(project_id: str, patient_id: str) -> str:
    return f"/v1/projects/{project_id}/test-patients/{patient_id}/consent"


# Build the body for CREATING a test patient
def _create_payload(summary: PatientSummary) -> dict[str, Any]:
    return {
        "firstName": summary.first_name or "Test",
        "lastName": summary.last_name or "Patient",
    }


# Build a per-patient object for the ADD-TO-PROJECT call
# Uses the real server-generated email captured at creation
# and includes contactPreference alongside languagePreference
def _add_payload(created: "CreatedPatient") -> dict[str, Any]:
    return {
        "email": created.email,
        "firstName": created.summary.first_name or "Test",
        "lastName": created.summary.last_name or "Patient",
        "languagePreference": "es" if created.summary.language == "es" else "en",
        "contactPreference": "email",
    }


# What we get back after creating a test patient
@dataclass
class CreatedPatient:
    summary: PatientSummary
    patient_id: str
    email: Optional[str] = None
    password: Optional[str] = None


# Create one test patient
# Capture id, email, and one-time password
def create_test_patient(
    client: HealthExClient, org_id: str, summary: PatientSummary
) -> CreatedPatient:
    body = client.post(_create_test_patient_path(org_id), json=_create_payload(summary))
    body = body or {}
    pid = body.get("id")
    if not pid:
        raise HealthExAPIError(f"create test patient returned no id: {body}")
    return CreatedPatient(
        summary=summary,
        patient_id=pid,
        email=body.get("email"),
        password=body.get("password"),
    )


# Add test patients to project in a single batch
def add_patients_to_project(
    client: HealthExClient, project_id: str, created: list[CreatedPatient]
) -> dict[str, Any]:
    payload = {
        "patients": [_add_payload(c) for c in created],
        "suppressNotifications": True,
    }
    return client.post(_add_patients_path(project_id), json=payload) or {}


# Opt a test patient in using patient token from
# the credentials captured at creation and
# call consent with that token
def set_consent(
    project_id: str,
    created: CreatedPatient,
    *,
    base_url: str = "https://api.healthex.io",
    status: str = "OPTED_IN",
) -> Any:
    if not created.email or not created.password:
        raise HealthExAPIError(
            f"missing patient credentials for {created.summary.full_name}; "
            "cannot mint patient token for consent"
        )
    # 1) Create patient token from the patient's own email/password
    try:
        token = patient_token(created.email, created.password, base_url=base_url)
    except AuthError as exc:
        raise HealthExAPIError(f"patient token failed: {exc}") from exc

    # 2) Call consent with the PATIENT token
    import requests

    url = f"{base_url.rstrip('/')}{_consent_path(project_id, created.patient_id)}"
    resp = requests.post(
        url,
        json={"consentStatus": status},
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        timeout=30,
    )
    if not resp.ok:
        raise HealthExAPIError(
            f"consent failed ({resp.status_code}): {resp.text}",
            status=resp.status_code,
            body=resp.text,
        )
    return resp.json() if resp.content else None


# Dry Run: Print the exact endpoints + payloads
# for the full sequence WITHOUT sending anything
# Uses the same builder functions as the real path
# so what's shown is exactly what would be sent
def dry_run(
    org_id: str,
    project_id: str,
    summaries: list[PatientSummary],
    *,
    do_consent: bool = True,
    base_url: str = "https://api.healthex.io",
) -> None:
    import json

    base = base_url.rstrip("/")

    def show(method: str, path: str, body: Any = None) -> None:
        print(f"\n{method} {base}{path}")
        if body is not None:
            print(json.dumps(body, indent=2))

    print(f"=== DRY RUN: {len(summaries)} patient(s), no requests will be sent ===")

    # Step 1: create each test patient
    print("\n--- Step 1: create test patients ---")
    for s in summaries:
        show("POST", _create_test_patient_path(org_id), _create_payload(s))

    # Step 2: add to project (single batch)
    # Uses placeholders for the email
    print("\n--- Step 2: add patients to project (single batch) ---")
    placeholder_created = [
        CreatedPatient(
            summary=s,
            patient_id="<id-from-create-response>",
            email="test-patient+<random>@<org-domain>",
            password="<from-create-response>",
        )
        for s in summaries
    ]
    add_body = {
        "patients": [_add_payload(c) for c in placeholder_created],
        "suppressNotifications": True,
    }
    show("POST", _add_patients_path(project_id), add_body)

    # Step 3: consent (per patient, using a patient token)
    if do_consent:
        print("\n--- Step 3: consent (per patient, uses PATIENT token) ---")
        print("  (first mints a patient token:)")
        show(
            "POST",
            "/v1/auth/token",
            {
                "email": "test-patient+<random>@<org-domain>",
                "password": "<from-create-response>",
            },
        )
        print("  (then calls consent with that patient token:)")
        for c in placeholder_created:
            show(
                "POST",
                _consent_path(project_id, c.patient_id),
                {"consentStatus": "OPTED_IN"},
            )

    print("\n=== END DRY RUN (nothing was sent) ===")


# Run the full sequence and return created patients
# Returns the created patients (with ids) so
# the FHIR step has something to verify
def upload(
    client: HealthExClient,
    org_id: str,
    project_id: str,
    summaries: list[PatientSummary],
    *,
    do_consent: bool = True,
    base_url: str = "https://api.healthex.io",
) -> list[CreatedPatient]:

    created: list[CreatedPatient] = []
    for summary in summaries:
        try:
            created.append(create_test_patient(client, org_id, summary))
        except HealthExAPIError as exc:
            print(f"create failed for {summary.full_name}: {exc}")

    if not created:
        print("No patients were created; nothing to add or consent.")
        return created

    if created:
        result = add_patients_to_project(client, project_id, created)
        print(
            "add-to-project: "
            f"success={result.get('successCount')} "
            f"errors={result.get('errorCount')} "
            f"duplicates={result.get('duplicatesCount')}"
        )

    if do_consent:
        for c in created:
            try:
                set_consent(project_id, c, base_url=base_url)
            except HealthExAPIError as exc:
                print(f"consent failed for {c.summary.full_name}: {exc}")

    return created
