import re
from collections import defaultdict
from decimal import Decimal

from app.models import Document, Observation
from ingestion.observations import ALIASES
from rag.repository import observation_query

REQUIRED_CONTEXT = {"feedstock", "reactor", "temperature", "pressure", "basis", "method"}
FACETS = {
    "objective": r"\b(?:objective|aim(?:s|ed)?|purpose)\b",
    "methodology": r"\b(?:methodology|method|protocol)\b",
    "experimental_setup": r"\b(?:experimental setup|reactor|apparatus)\b",
    "simulation_model": r"\b(?:simulation|model predicted|computational model)\b",
    "materials": r"\b(?:feedstock|materials|catalysts?)\b",
    "conditions": r"\b(?:conditions|temperature|pressure)\b",
    "assumptions": r"\b(?:assumption|assumed|equation)\b",
    "results": r"\b(?:result|results|observed|measured)\b",
    "performance": r"\b(?:efficiency|conversion|yield|performance)\b",
    "limitations": r"\b(?:limitation|limitations|limited)\b",
    "gaps": r"\b(?:gap|gaps|unresolved)\b",
    "future_work": r"\b(?:future work|future research|further studies)\b",
}


def facets(text):
    return [key for key, expression in FACETS.items() if re.search(expression, text, re.I)]


def observation_data(row, document):
    return {"id": row.id, "passage_id": row.passage_id, "document_id": document.id, "title": document.title,
            "metric": row.metric, "value": row.raw_value, "unit": row.unit, "study_type": row.study_type,
            "conditions": row.conditions, "confidence": row.confidence}


def compare(db, project_id, document_ids, metric):
    query = observation_query(project_id).where(Observation.metric == ALIASES.get(metric.lower(), metric.lower()))
    if document_ids:
        query = query.where(Document.id.in_(document_ids))
    groups = defaultdict(list)
    incomplete = []
    for row, document in db.execute(query.order_by(Observation.id).limit(200)):
        item = observation_data(row, document)
        if row.study_type not in ("experiment", "simulation") or not REQUIRED_CONTEXT.issubset(row.conditions):
            incomplete.append(item)
            continue
        key = (row.unit, row.study_type, tuple(sorted(row.conditions.items())))
        groups[key].append(item)
    matches = []
    for (unit, study, conditions), rows in groups.items():
        if len({item["document_id"] for item in rows}) < 2:
            incomplete.extend(rows)
            continue
        values = [Decimal(item["value"]) for item in rows]
        differs = min(values) != max(values)
        matches.append({"unit": unit, "study_type": study, "conditions": dict(conditions), "rows": rows,
                        "observed_span": str(max(values) - min(values)), "differing_values": differs,
                        "disagreement": "review_uncertainty" if differs else "no_difference_detected"})
    return {"matched": matches, "unmatched": incomplete,
            "interpretation": "Extracted values require source review. Differing values alone do not establish a contradiction."}
