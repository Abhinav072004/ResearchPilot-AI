import re
from decimal import Decimal, InvalidOperation

from ingestion.domains import METRIC_DOMAINS, SCHEMAS, Domain

ALIASES = {"cge": "cold gas efficiency", "cce": "carbon conversion efficiency", "hhv": "higher heating value"}
METRICS = (*METRIC_DOMAINS, *ALIASES)
VALUE = r"[-+]?(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][-+]?\d{1,2})?"
NAMES = "|".join(re.escape(name) for name in sorted(METRICS, key=len, reverse=True))
UNITS = "|".join(re.escape(unit) for unit in sorted(
    {unit for schema in SCHEMAS.values() for units in schema.metrics.values() for unit in units}, key=len, reverse=True
))
PATTERN = re.compile(rf"\b(?P<metric>(?i:{NAMES}))\s*(?i:was|of|=|:)\s*(?P<value>{VALUE})(?!\d|\.\d|[eE][+-]?\d)"
                     rf"(?:\s*(?P<unit>{UNITS})(?![\w/])|(?=\s*[,;.)]|\s*$))")
TEXT_CONTEXT = {key for schema in SCHEMAS.values() for key in schema.required_context} - {"temperature", "pressure"}
TEXT_CONTEXT.add("catalyst")
CONDITIONS = {
    "temperature": rf"\btemperature\s*(?:of|was|=|:)\s*({VALUE}\s*(?:°C|K))",
    "pressure": rf"\bpressure\s*(?:of|was|=|:)\s*({VALUE}\s*(?:kPa|MPa|bar|atm|Pa))",
    "equivalence_ratio": rf"\bequivalence ratio\s*(?:of|was|=|:)\s*({VALUE})",
    "steam_to_biomass_ratio": rf"\bsteam[- ]to[- ]biomass ratio\s*(?:of|was|=|:)\s*({VALUE})",
    **{key: rf"\b{re.escape(key)}\s*[:=]\s*([\w /+()-]{{1,80}})(?=[,;.]|$)" for key in TEXT_CONTEXT},
}
AMBIGUOUS = re.compile(
    rf"\b(?:at least|at most|more than|less than|approximately|up to|ranged|between)\b|±"
    rf"|\d(?:\s*(?:{UNITS}))?\s*[-–—]\s*\d",
    re.I,
)
STUDY_MARKERS = {
    "experiment": r"\b(?:experimentally|experiment|experiments|measured|trial)\b",
    "simulation": r"\b(?:simulated|simulation|simulations|model predicted)\b",
    "review": r"\b(?:review|reviews|meta.analysis)\b",
}


def canonical_metric(name):
    return ALIASES.get(name.casefold(), name.casefold())


def mentioned_metrics(text, domain=Domain.AUTO):
    return {metric for name in METRICS if re.search(rf"(?<!\w){re.escape(name)}(?!\w)", text, re.I)
            if (metric := canonical_metric(name)) and (domain == Domain.AUTO or METRIC_DOMAINS[metric] == domain)}


def extract(text):
    for sentence in re.split(r"(?<=[.!?])\s+(?=[A-Z])", text):
        if AMBIGUOUS.search(sentence):
            continue
        markers = [tag for tag, pattern in STUDY_MARKERS.items() if re.search(pattern, sentence, re.I)]
        study = markers[0] if len(markers) == 1 else "unknown"
        conditions = {}
        for key, pattern in CONDITIONS.items():
            values = [" ".join(m.split()) for m in re.findall(pattern, sentence, re.I)]
            matches = set(values if key in ("temperature", "pressure") else (value.casefold() for value in values))
            if len(matches) == 1:
                conditions[key] = matches.pop()
        for match in PATTERN.finditer(sentence):
            metric = canonical_metric(match["metric"])
            domain = METRIC_DOMAINS[metric]
            raw, unit = match["value"], match["unit"] or "unitless"
            if unit not in SCHEMAS[domain].metrics[metric]:
                continue
            try:
                value = float(Decimal(raw))
            except (InvalidOperation, OverflowError):
                continue
            if -1e30 < value < 1e30:
                yield dict(metric=metric, raw_value=raw, value=value, unit=unit, domain=domain.value,
                           study_type=study, conditions=conditions, confidence="unreviewed")


def extract_table(table):
    """Extract numeric cells only when a unique header explicitly identifies metric and unit."""
    cells = table["cells"]
    headers = {}
    for item in cells:
        if item["header"] and item["colspan"] == 1:
            headers.setdefault(item["column"], set()).add(item["text"])
    keys = {}
    for column, labels in headers.items():
        if len(labels) != 1:
            continue
        header = next(iter(labels))
        match = re.fullmatch(r"(.+?)\s*\(([^()]+(?:\([^()]*\)[^()]*)?)\)", header)
        name, unit = match.groups() if match else (header, "unitless")
        metric = canonical_metric(name.strip())
        domain = METRIC_DOMAINS.get(metric)
        if domain and unit in SCHEMAS[domain].metrics[metric]:
            keys[column] = (metric, unit)
    rows = {}
    for item in cells:
        if item["header"]:
            continue
        rows.setdefault(item["row"], []).append(item)
    for row_cells in rows.values():
        context = "; ".join(f"{next(iter(headers[item['column']]))}: {item['text']}"
                            for item in row_cells if len(headers.get(item["column"], ())) == 1)
        for item in row_cells:
            if item["column"] not in keys or item["colspan"] != 1 or item["rowspan"] != 1:
                continue
            raw = item["text"]
            if not re.fullmatch(VALUE, raw):
                continue
            metric, unit = keys[item["column"]]
            measurement = f"{table['caption'].strip().rstrip('.')}; {metric}: {raw} {unit}; {context}"
            for observation in extract(measurement):
                if observation["metric"] == metric and observation["raw_value"] == raw:
                    yield {**observation, "measurement_anchor": {"row": item["row"], "column": item["column"]}}
                    break
