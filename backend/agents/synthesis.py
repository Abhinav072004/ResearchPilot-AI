"""Bounded structured claim proposals and independent evidence judgments."""

from pydantic import BaseModel, Field, ValidationError


class Support(BaseModel):
    id: str = Field(min_length=1, max_length=36)
    quote: str = Field(min_length=20, max_length=500)


class ProposedClaim(BaseModel):
    text: str = Field(min_length=15, max_length=450)
    supports: list[Support] = Field(min_length=1, max_length=3)


class Synthesis(BaseModel):
    claims: list[ProposedClaim] = Field(min_length=0, max_length=5)


def propose(model, question, passages):
    result = model.ask(
        "Propose up to five cautious, atomic scientific findings answering the question. "
        "Return JSON with a claims array. Each claim must contain text and supports, with "
        "one to three objects that each contain a supplied passage id and an exact verbatim quote. "
        "Distinguish study methods and qualifiers. Do not add numeric values absent from the quotes.",
        {"query": question, "passages": [
            {"id": row.id, "section": row.section[:160], "text": row.text[:1200]} for row in passages[:8]
        ]},
        1400,
    )
    try:
        return Synthesis.model_validate(result).claims
    except ValidationError:
        return []


def verify(model, proposals, passages):
    valid = {}
    for proposal in proposals:
        try:
            claim = ProposedClaim.model_validate(proposal)
        except ValidationError:
            continue
        if all(support.id in passages and support.quote in passages[support.id].text for support in claim.supports):
            valid[str(len(valid))] = claim
    if not valid:
        return []
    result = model.ask(
        "Independently judge entailment. Accept a claim only if its supplied quotes directly support the entire claim, "
        "including values, attribution, limitations, experimental or simulation method and scope. "
        "Reject speculation, causal leaps and incompatible comparisons. Return a JSON object with an accepted array "
        "containing the string IDs of accepted claims only.",
        {"claims": [{"id": key, "text": item.text, "quotes": [ref.quote for ref in item.supports]}
                    for key, item in valid.items()]},
        350,
    )
    accepted = result.get("accepted")
    if not isinstance(accepted, list):
        return []
    return [valid[key] for key in dict.fromkeys(item for item in accepted if isinstance(item, str)) if key in valid]
