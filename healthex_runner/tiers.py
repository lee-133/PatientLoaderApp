# Complexity-tier lookup, sourced from dataset's own index.html
#
# The four tiers (Exceptionally Healthy / Generally Healthy / Chronic /
# Complex) aren't in the FHIR bundles. The dataset contains an index.html 
# that lists each patient under a tier heading and links them to their bundle file
# so we parse it into a {filename -> tier} map
#
# The mapping is matched by filename, not patient name
# extract.py resolves each bundle's tier by its filename
# reliable because the published roster includes middle names
# the bundles don't carry, so name-matching would miss
#
# Reads only files provided in the dataset: no network calls


from __future__ import annotations
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Optional

TIERS = (
    "exceptionally_healthy",
    "generally_healthy",
    "chronic_conditions",
    "complex_conditions",
)

TIER_LABELS = {
    "exceptionally_healthy": "Exceptionally Healthy",
    "generally_healthy": "Generally Healthy",
    "chronic_conditions": "Chronic Conditions",
    "complex_conditions": "Complex Conditions",
}

# Map the human-readable heading to a key
_LABEL_TO_KEY = {label: key for key, label in TIER_LABELS.items()}


def _label_to_key(heading: str) -> Optional[str]:
    clean = re.sub(r"\s*\(\d+\)\s*$", "", heading).strip()
    return _LABEL_TO_KEY.get(clean)


# Track <h3> heading and associate
# each subsequent .json link with that tier
class _IndexParser(HTMLParser):

    def __init__(self) -> None:
        super().__init__()
        self._current_tier: Optional[str] = None
        self._in_h3 = False
        self._h3_text = ""
        self.file_to_tier: dict[str, str] = {}

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if tag == "h3":
            self._in_h3 = True
            self._h3_text = ""
        elif tag == "a":
            href = d.get("href")
            if href and href.endswith(".json") and self._current_tier:
                filename = href.split("/")[-1]
                self.file_to_tier[filename] = self._current_tier

    def handle_endtag(self, tag):
        if tag == "h3":
            self._in_h3 = False
            self._current_tier = _label_to_key(self._h3_text)

    def handle_data(self, data):
        if self._in_h3:
            self._h3_text += data


# Index.html parser
# Return {json_filename -> tier_key}
def load_index(index_path: str | Path) -> dict[str, str]:
    text = Path(index_path).read_text(encoding="utf-8")
    parser = _IndexParser()
    parser.feed(text)
    return parser.file_to_tier


# Return tier key for bundle filename
def tier_for_filename(filename: str, file_to_tier: dict[str, str]) -> Optional[str]:
    return file_to_tier.get(Path(filename).name)
