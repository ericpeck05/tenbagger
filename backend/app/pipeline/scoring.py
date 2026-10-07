"""Keep each company's Lynch category, score, and nine tests current on its ratios row."""

import json

from sqlalchemy.orm import Session

from app.db.models import RATIO_COLUMNS, Company, Ratio
from app.pipeline import lynch


def refresh_lynch(session: Session, row: Ratio, company: Company | None = None) -> None:
    company = company or session.get(Company, row.cik)
    inputs = {c: getattr(row, c) for c in RATIO_COLUMNS}
    out = lynch.evaluate(
        inputs, company.sector if company else None, company.sic_code if company else None
    )
    row.lynch_category = out["category"]
    row.lynch_score = out["score"]
    row.lynch_tests = json.dumps(out["tests"])
