"""Limit/offset paging with a total count, shared by all list endpoints."""

from fastapi import Response
from sqlalchemy import Result, Select, func, select
from sqlalchemy.orm import Session

# Total number of matching rows (before limit/offset), so a UI can show "page 2 of 7".
# A browser frontend on another origin must be allowed to read it via CORS
# `expose_headers` (set up with the frontend in P6).
TOTAL_COUNT_HEADER = "X-Total-Count"


def fetch_page(
    session: Session, query: Select, limit: int, offset: int, response: Response
) -> Result:
    """Run `query` for one page and put the total match count in the response header."""
    # Ordering does not change a count, so it is dropped from the count query.
    count_query = select(func.count()).select_from(query.order_by(None).subquery())
    response.headers[TOTAL_COUNT_HEADER] = str(session.execute(count_query).scalar_one())
    return session.execute(query.limit(limit).offset(offset))
