import re
from decimal import Decimal, InvalidOperation

METRICS = ("hydrogen yield", "carbon conversion efficiency", "cold gas efficiency", "conversion",
           "higher heating value", "tar concentration", "syngas yield", "CGE", "CCE", "HHV")
VALUE = r"[-+]?(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][-+]?\d{1,2})?"
PATTERN = re.compile(rf"\b({'|'.join(METRICS)})\s*(?:was|of|=|:)\s*({VALUE})\s*"
                     r"(%|mol/kg|mmol/g|g/kg|mg/m³|MJ/kg|L/kg)(?![\w/])", re.I)
CONDITIONS = {
    "temperature": rf"\btemperature\s*(?:of|was|=|:)\s*({VALUE}\s*(?:°C|K))",
    "pressure": rf"\bpressure\s*(?:of|was|=|:)\s*({VALUE}\s*(?:kPa|MPa|bar|atm|Pa))",
    "equivalence_ratio": rf"\bequivalence ratio\s*(?:of|was|=|:)\s*({VALUE})",
    "steam_to_biomass_ratio": rf"\bsteam[- ]to[- ]biomass ratio\s*(?:of|was|=|:)\s*({VALUE})",
    **{key: rf"\b{key}\s*[:=]\s*([\w -]{{1,60}})(?=[,;.])"
       for key in ("feedstock", "reactor", "catalyst", "basis", "method")},
}
ALIASES = {"cge": "cold gas efficiency", "cce": "carbon conversion efficiency", "hhv": "higher heating value"}


def extract(text):
    for sentence in re.split(r"(?<=[.!?])\s+(?=[A-Z])", text):
        lowered = sentence.lower()
        markers = [tag for tag, pattern in {
            "experiment": r"\b(?:experimentally|experiment|experiments|measured)\b",
            "simulation": r"\b(?:simulated|simulation|simulations|model predicted)\b",
            "review": r"\b(?:review|reviews)\b",
        }.items() if re.search(pattern, lowered)]
        study = markers[0] if len(markers) == 1 else "unknown"
        conditions = {}
        for key, pattern in CONDITIONS.items():
            values = [" ".join(m.split()) for m in re.findall(pattern, sentence, re.I)]
            matches = set(values if key in ("temperature", "pressure") else (value.casefold() for value in values))
            if len(matches) == 1:
                conditions[key] = matches.pop()
        if re.search(r"\b(?:at least|at most|more than|less than|approximately|up to|ranged|between)\b|±", lowered):
            continue
        for match in PATTERN.finditer(sentence):
            metric, raw, unit = match.groups()
            try:
                value = float(Decimal(raw))
            except (InvalidOperation, OverflowError):
                continue
            if not -1e30 < value < 1e30:
                continue
            yield dict(metric=ALIASES.get(metric.lower(), metric.lower()), raw_value=raw, value=value,
                       unit=unit, study_type=study, conditions=conditions, confidence="unreviewed")
