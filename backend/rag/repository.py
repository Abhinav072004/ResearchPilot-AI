from sqlalchemy import String, func, literal_column, select

from app.models import Document, Observation, Paper, Passage, Section
from ingestion.observations import ALIASES, METRICS
from rag.engine import Evidence, Vectorless, plan, tokens


def evidence_query(project_id):
    return (select(Passage, Section, Document, Paper)
            .join(Section, Passage.section_id == Section.id)
            .join(Document, Section.document_id == Document.id)
            .outerjoin(Paper, Document.paper_id == Paper.id)
            .where(Document.project_id == project_id))


def evidence(row):
    passage, section, document, paper = row
    return Evidence(id=passage.id, document_id=document.id, title=document.title, text=passage.text,
                    section=section.heading, section_id=section.id, kind=passage.kind, page=passage.page,
                    doi=paper.doi if paper else None, access=document.access,
                    metadata={**paper.metadata_json, "document_link": "user_asserted", **(document.provenance or {}),
                              "retracted": True if paper.retracted else paper.metadata_json.get("retracted")}
                    if paper else {}, anchor=passage.anchor)


def observation_query(project_id):
    return (select(Observation, Document).join(Passage, Observation.passage_id == Passage.id)
            .join(Section, Passage.section_id == Section.id).join(Document, Section.document_id == Document.id)
            .outerjoin(Paper, Document.paper_id == Paper.id)
            .where(Document.project_id == project_id, (Paper.id.is_(None) | Paper.retracted.is_(False))))


def retrieve(db, project_id, query, limit=10, *, document_ids=(), year=None, metric=None,
             unit=None, minimum=None, maximum=None, reranker=None):
    selection = evidence_query(project_id).where(Paper.id.is_(None) | Paper.retracted.is_(False))
    if document_ids:
        selection = selection.where(Document.id.in_(document_ids))
    if year:
        selection = selection.where(Paper.metadata_json["year"].as_string().cast(String) == str(year))

    def numerical(text):
        metrics = {ALIASES.get(key.lower(), key.lower()) for key in METRICS if key.lower() in text.lower()}
        if metric:
            metrics = {ALIASES.get(metric.lower(), metric.lower())}
        if not metrics and unit is None and minimum is None and maximum is None:
            return []
        statement = observation_query(project_id).with_only_columns(Observation.passage_id)
        if metrics:
            statement = statement.where(Observation.metric.in_(metrics))
        if unit is not None:
            statement = statement.where(Observation.unit == unit)
        if minimum is not None:
            statement = statement.where(Observation.value >= minimum)
        if maximum is not None:
            statement = statement.where(Observation.value <= maximum)
        return db.scalars(statement.order_by(Observation.id).limit(200)).all()

    ordered = selection.order_by(Document.id, Passage.ordinal, Passage.id)
    if any(value is not None for value in (metric, unit, minimum, maximum)):
        selection = selection.where(Passage.id.in_(numerical(query)))
        ordered = selection.order_by(Document.id, Passage.ordinal, Passage.id)
    routing = plan(query)
    if routing.doi:
        rows = db.execute(ordered.where(Paper.doi == routing.doi).limit(limit)).all()
    else:
        ids = db.scalars(ordered.with_only_columns(Passage.id).limit(4001)).all()
        if len(ids) <= 4000:
            rows = db.execute(ordered).all()
        else:
            if db.get_bind().dialect.name != "postgresql":
                raise ValueError("Filter by document or year to search more than 4,000 SQLite passages.")
            keywords = list(dict.fromkeys(tokens(query)))[:24]
            if not keywords:
                return []
            lexicon = literal_column("'simple'::regconfig")
            tsquery = func.plainto_tsquery(lexicon, keywords[0])
            for keyword in keywords[1:]:
                tsquery = tsquery.op("||")(func.plainto_tsquery(lexicon, keyword))
            tsvector = func.to_tsvector(lexicon, Passage.text)
            metadata = func.to_tsvector(lexicon, Document.title + " " +
                                        func.coalesce(Paper.metadata_json.cast(String), ""))
            ids = set(numerical(query)) if "sql" in routing.routes else set()
            # Two independent lists preserve metadata and numerical hits outside the text shortlist.
            text_hits = selection.where(tsvector.bool_op("@@")(tsquery)).order_by(
                func.ts_rank_cd(tsvector, tsquery).desc(), Passage.id).limit(3000)
            supplemental = ordered.where(metadata.bool_op("@@")(tsquery) | Passage.id.in_(ids)).limit(1000)
            rows = list({row[0].id: row for row in [*db.execute(text_hits), *db.execute(supplemental)]}.values())
    corpus = [evidence(row) for row in rows]
    return Vectorless(corpus, numerical=numerical, reranker=reranker).search(query, limit)
