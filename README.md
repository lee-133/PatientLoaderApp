# HealthEx Patient Loader

A lightweight Python CLI that loads sample patient FHIR bundles into a HealthEx project. It reads the provided sample dataset, lets you select patients either in full or by a set of filters (complexity tier, condition, age, gender, language, state), creates them as test patients, adds them to a project, handles patient consent, and verifies the whole pipeline by calling the FHIR `$everything` API and printing the returned record.

## What it does

Given the HealthEx sample patient dataset, the tool runs this pipeline:

1. **Read & summarize**: each FHIR bundle is parsed once into a compact summary (name, age, gender, language, state, complexity tier, active conditions).
2. **Select**: upload everyone, or filter to a subset by tier, condition keyword, age range, gender, language, or state. Filters combine with AND logic.
3. **Create test patients**: one create call per selected patient; the API returns each patient's id, email, and one-time password.
4. **Add to project**: a single batched call adds the selected patients to the
   target project.
5. **Consent**: each patient is opted in. Consent is performed *as the patient*, using a token generated from that patient's own credentials, because the FHIR data is only retrievable once the patient has consented.
6. **Verify via FHIR**: the tool calls `GET /FHIR/R4/Person/{id}/$everything` for one created patient and prints the returned FHIR bundle, proving the round trip.

## How complexity tiers work

The four complexity tiers (Exceptionally Healthy, Generally Healthy, Chronic Conditions, Complex Conditions). They come from the dataset's own `index.html` which lists each patient under a tier heading and links them to their bundle file. The tool parses that file to map each bundle to its tier by filename. This keeps the classification authoritative (it's HealthEx's own grouping) and requires no network calls.

## Requirements

- Python 3.10+ (developed on 3.14)
- The HealthEx sample patient dataset (see **Getting the data** below)
- HealthEx API credentials (API key + secret) for a provisioned organization

## Getting the data

The sample patient dataset is **not included in this repository**. To run the tool, request the HealthEx sample patient archive separately, then unzip its contents into a `patientData/` folder at the project root. The folder should contain the patient bundle files (`*.json`) and the `index.html` index that the tool uses to resolve complexity tiers.

```
HealthEx-patient-loader/
├── patientData/
│   ├── index.html
│   ├── <uuid>.json
│   ├── <uuid>.json
│   └── ...
```

## Setup

```bash
# 1. Clone and enter the project
git clone <your-repo-url>
cd HealthEx-patient-loader

# 2. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Create your config from the template and fill in your credentials
cp config.example.json config.json
#    then edit config.json with your apiKey, apiSecret, orgId, projectId

# 5. Add the sample dataset
#    unzip the HealthEx sample archive into ./patientData/
```

### Configuration

`config.json` holds your credentials and target project. The fields:

| Field        | Description                                              |
|--------------|----------------------------------------------------------|
| `apiKey`     | Your HealthEx API key                                    |
| `apiSecret`  | Your HealthEx API secret                                 |
| `orgId`      | Your organization ID                                     |
| `projectId`  | The project to add patients to                           |

If you don't know your `orgId` or `projectId`, they can be discovered from the `search-for-studies` API (each study result carries the project `id` and the owning `addedByOrganization.id`).

## Usage

### Dry Run (recommended first)

Preview every request the tool would send without sending anything or needing valid credentials:

```bash
python main.py --dry-run
```

### Live Run

```bash
python main.py
```

You'll be prompted to upload all patients or filter, then to confirm before anything is created. After upload, the tool runs FHIR verification on the first patient and prints the returned bundle.

### Options

| Flag            | Description                                                    |
|-----------------|----------------------------------------------------------------|
| `--dry-run`     | Print endpoints and payloads without sending requests          |
| `--no-consent`  | Skip the consent step (FHIR verification will then fail w/ 403)|
| `--config PATH` | Path to the config file (default: `config.json`)               |
| `--data PATH`   | Path to the patient data folder (default: `patientData`)       |

### Example Session

```
$ python main.py
Reading bundles from patientData ...
Loaded 125 patients (125 with a tier from index.html).

Upload [a]ll patients or [f]ilter? (a/f): f

Complexity tiers:
  1. Exceptionally Healthy
  2. Generally Healthy
  3. Chronic Conditions
  4. Complex Conditions
Tiers to include (e.g. '3,4', blank = any): 1
Condition keyword(s), comma-separated (blank = any):
Min age (blank = none): 69
Max age (blank = none): 69
Gender (male/female, blank = any):
Language code (en/es, blank = any):
State (e.g. 'New York', blank = any):

1 patient(s) matched:
  Hayden Schroeder             age  69  male    5 cond  [Exceptionally Healthy]

This will create 1 test patient(s) ...
Proceed with upload? [y/N]: y
add-to-project: success=1 errors=0 duplicates=0
Created 1 test patient(s).

Verifying via FHIR $everything for Hayden Schroeder ...
FHIR round trip succeeded — the patient's data is retrievable.

--- Full FHIR bundle ---
{ ... full FHIR JSON ... }
```

## Project Structure

```
HealthEx-patient-loader/
├── healthex_runner/        # the package
│   ├── __init__.py
│   ├── cli.py              # interactive flow, argument parsing
│   ├── auth.py             # org JWT + patient token generation
│   ├── client.py           # thin authenticated HTTP layer
│   ├── extract.py          # FHIR bundle -> PatientSummary
│   ├── tiers.py            # index.html -> complexity tier lookup
│   ├── filters.py          # composable patient filters
│   ├── loader.py           # create / add-to-project / consent workflow
│   └── fhir.py             # FHIR $everything verification
├── main.py                 # entry point (python main.py)
├── config.example.json     # credential template (copy to config.json)
├── requirements.txt
└── patientData/            # sample dataset (provided separately, gitignored)
```

## Design Notes

- **Two-layer architecture**: `client.py` is a thin HTTP layer that knows nothing about patients; `loader.py` and `fhir.py` hold the domain logic and call the client. This keeps auth-header and error handling in one place.
- **Extract-then-filter**: Each bundle is parsed once into a small summary, so filtering across the full dataset is cheap rather than re-reading large files.
- **Composable filters**: Each filter is a single predicate function; adding a new filter dimension is a one-function change.
- **Patient-scoped consent**: Consent uses a token generated from the patient's own credentials, matching the API's requirement that consent be given as the patient.
- **Language handling**: The API supports only `en` and `es`; any other language in the source data is mapped to `en` so the add call succeeds.
- **Resilient bulk operations**: Both patient creation and consent tolerate per-patient failures: a failed call is logged and skipped rather than aborting the whole batch, so one bad record doesn't strand the patients already processed.

## Notes

- Tier matching is done by bundle filename (via `index.html`) rather than by patient name.
- For a large selection, the tool makes one create call and one consent flow per patient (sequentially), so a full-dataset run takes some time.
- If an individual call fails, that patient is skipped with a logged warning and the run continues.
