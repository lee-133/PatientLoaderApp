# Interactive CLI: filter sample patients and upload them to a project
#
# This is the orchestration layer: it drives the flow and calls into the other modules
# (extract, filters, loader, fhir)
# it holds no API logic itself
#
# Flow:
#  1. Load config (apiKey/apiSecret/orgId/projectId)
#  2. Summarize the data folder (bundles + index.html for tiers)
#  3. Ask: upload ALL, or FILTER by
#  4. If filtering, collect filters (tier / condition / age / gender / language / state)
#       Re-prompts on invalid input
#       Allows blank entries for filters as well
#  5. Show matched test patients and confirm before anything is sent
#       Can re-filter if needed
#  6. Authenticate -> create test patients -> add to project -> set consent
#  7. Verify one patient via the FHIR $everything API and print the result
#
# Also has --dry-run option to test printing requests
# without sending any actual data/requests


from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from typing import Optional
from .auth import HealthExAuth, AuthError
from .client import HealthExClient, HealthExAPIError
from .extract import PatientSummary, summarize_dir
from .tiers import TIERS, TIER_LABELS
from . import filters as F
from . import loader
from . import fhir


# Config loader
def load_config(path: Path) -> dict:
    if not path.exists():
        sys.exit(f"config not found: {path}\nCopy config.example.json and fill it in.")
    cfg = json.loads(path.read_text())
    missing = [
        k for k in ("apiKey", "apiSecret", "orgId", "projectId") if not cfg.get(k)
    ]
    if missing:
        sys.exit(f"config missing required fields: {', '.join(missing)}")
    return cfg


# Small input helpers
def _prompt(msg: str) -> str:
    try:
        return input(msg).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit("cancelled.")


def _confirm(msg: str) -> bool:
    return _prompt(f"{msg} [y/N]: ").lower() in ("y", "yes")


def _prompt_int(msg: str) -> Optional[int]:
    # Prompt for an integer. Blank returns None (skip)
    # Re-prompts on non-numeric input rather than silently skipping
    while True:
        raw = _prompt(msg)
        if not raw:
            return None
        try:
            return int(raw)
        except ValueError:
            print("  Please enter a whole number, or leave blank to skip.")


def _prompt_choice(msg: str, allowed: dict[str, str]) -> Optional[str]:
    # Prompt until the input matches an allowed value, or is blank
    # `allowed` maps accepted inputs (lowercased) to the canonical value
    # returned, e.g. {"male": "male", "m": "male", "female": "female", "f":
    # "female"}. Input is matched case-insensitively. On an unrecognized
    # entry, the user is told the valid options and asked again.

    options = sorted(set(allowed.values()))
    while True:
        raw = _prompt(msg).lower()
        if not raw:
            return None
        if raw in allowed:
            return allowed[raw]
        print(f"  Please enter one of: {', '.join(options)} (or leave blank to skip).")


# Filter collection
# These are the available filter options that
# can be selected when selecting patients
def collect_filters(summaries: list[PatientSummary]) -> list:
    preds = []

    # tier
    print("\nComplexity tiers:")
    for i, t in enumerate(TIERS, 1):
        print(f"  {i}. {TIER_LABELS[t]}")
    while True:
        raw = _prompt("Tiers to include (e.g. '3,4', blank = any): ")
        if not raw:
            break
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        valid = [p for p in parts if p.isdigit() and 1 <= int(p) <= len(TIERS)]
        if len(valid) != len(parts):
            print(
                f"  Please enter tier numbers between 1 and {len(TIERS)}, "
                "comma-separated (or leave blank for any)."
            )
            continue
        chosen = [TIERS[int(p) - 1] for p in valid]
        if chosen:
            preds.append(F.by_tier(*chosen))
        break

    # condition
    # free-text substring match; no fixed value set to validate against
    cond = _prompt("Condition keyword(s), comma-separated (blank = any): ")
    if cond:
        terms = [c.strip() for c in cond.split(",") if c.strip()]
        preds.append(F.has_condition(*terms))

    # age
    lo = _prompt_int("Min age (blank = none): ")
    hi = _prompt_int("Max age (blank = none): ")
    if lo is not None or hi is not None:
        preds.append(F.age_between(lo, hi))

    # gender
    gender = _prompt_choice(
        "Gender (male/female, blank = any): ",
        {"male": "male", "m": "male", "female": "female", "f": "female"},
    )
    if gender:
        preds.append(F.by_gender(gender))

    # language
    lang = _prompt_choice(
        "Language code (en/es, blank = any): ",
        {"en": "en", "english": "en", "es": "es", "spanish": "es"},
    )
    if lang:
        preds.append(F.by_language(lang))

    # state
    # free-text substring match; no fixed value set to validate against
    state = _prompt("State (e.g. 'New York', blank = any): ")
    if state:
        preds.append(F.by_state(state))

    return preds


# Show patient matches based on filters
# cap the printed list so a big match doesn't flood the terminal
def show_matches(matched: list[PatientSummary]) -> None:
    print(f"\n{len(matched)} patient(s) matched:")
    for s in matched[:50]:
        tier = TIER_LABELS.get(s.tier or "", "—")
        print(
            f"  {s.full_name:28s} age {str(s.age):>3}  {s.gender or '?':6s} "
            f"{s.active_condition_count:>2} cond  [{tier}]"
        )
    if len(matched) > 50:
        print(f"  ... and {len(matched) - 50} more")


# main
def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Filter and upload HealthEx sample patients."
    )
    parser.add_argument("--config", default="config.json", type=Path)
    parser.add_argument(
        "--data",
        default="patientData",
        type=Path,
        help="folder with test patient .json bundles and index.html",
    )
    parser.add_argument(
        "--no-consent",
        action="store_true",
        help="skip the consent step (FHIR verify will fail)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the exact endpoints/payloads without sending anything",
    )
    args = parser.parse_args(argv)

    cfg = load_config(args.config)

    print(f"Reading bundles from {args.data} ...")
    summaries = summarize_dir(args.data)
    if not summaries:
        sys.exit(f"no test patient bundles found in {args.data}")
    tiered = sum(1 for s in summaries if s.tier)
    print(
        f"Loaded {len(summaries)} test patients ({tiered} with a tier from index.html)."
    )

    # Select patients, with the ability to retry filtering. Loops until the
    # user confirms a non-empty selection (returns `matched`), or chooses to
    # quit / completes a dry run (returns early)
    while True:
        mode = _prompt("\nUpload [a]ll patients or [f]ilter? (a/f): ").lower()
        if mode.startswith("f"):
            preds = collect_filters(summaries)
            matched = F.apply(summaries, preds)
        else:
            matched = summaries

        if not matched:
            print("No patients matched those filters.")
            if _confirm("Try different filters?"):
                continue
            print("Nothing to upload. Exiting.")
            return 0

        show_matches(matched)

        # dry run: print payloads and stop, no auth or network needed
        if args.dry_run:
            print()
            loader.dry_run(
                cfg["orgId"],
                cfg["projectId"],
                matched,
                do_consent=not args.no_consent,
            )
            return 0

        # confirm the side-effectful part
        print(
            f"\nThis will create {len(matched)} test patient(s) in org {cfg['orgId']} "
            f"and add them to project {cfg['projectId']}."
        )
        if _confirm("Proceed with upload?"):
            break  # confirmed: leave the loop and upload

        # not confirmed: offer to re-filter rather than exit outright
        if not _confirm("Choose a different set?"):
            print("Stopped before uploading. No changes made.")
            return 0
        # otherwise loop back to the all/filter prompt

    # authenticate + build client
    try:
        auth = HealthExAuth(cfg["apiKey"], cfg["apiSecret"])
        auth.token()  # fail fast if credentials are wrong
    except AuthError as exc:
        sys.exit(f"authentication failed: {exc}")
    client = HealthExClient(auth)

    # upload
    try:
        created = loader.upload(
            client,
            cfg["orgId"],
            cfg["projectId"],
            matched,
            do_consent=not args.no_consent,
        )
    except HealthExAPIError as exc:
        sys.exit(f"upload failed: {exc}")
    print(f"\nCreated {len(created)} test patient(s).")

    # FHIR verification on the first created test patient
    if created:
        first = created[0]
        print(
            f"\nRun FHIR $everything API for test patient: {first.summary.full_name} "
            f"(id {first.patient_id}) ..."
        )
        try:
            info = fhir.verify_patient(client, first.patient_id)
            print(f"  name:            {info['name']}")
            print(f"  total resources: {info['total_resources']}")
            print(f"  resource counts: {info['resource_counts']}")
            print(f"  sample conditions: {info['sample_conditions']}")
            print("\n--- Full FHIR bundle ---")
            fhir.print_full_bundle(info["bundle"])
        except HealthExAPIError as exc:
            print(f"  FHIR verification failed: {exc}")
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
