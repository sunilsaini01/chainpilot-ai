"""Policy documents for the AI copilot: load them into `document_chunks` and search them.

Documents are the Markdown files in apps/api/policies/ (simulated company
policies written for the demo). Each `## ` section becomes one chunk; a very
long section is split at blank lines. A citation names the section:
policy:<document>#<section_slug>.

Search uses PostgreSQL full-text search with English stemming ("approvals"
finds "approve"). Any of the question's words may match, and chunks matching
more of them rank higher. It does not understand synonyms ("vendor" does not
find "supplier"); the retrieval check in docs/MODEL_RESULTS.md measures this.
"""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Text, cast, delete, func, select
from sqlalchemy.dialects.postgresql import TSQUERY
from sqlalchemy.orm import Session

from app.models import DocumentChunk

DEFAULT_FOLDER = Path(__file__).resolve().parents[1] / "policies"
DOCUMENT_NAME = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
MAX_CHUNK_CHARS = 1500
MAX_QUERY_CHARS = 200
OVERVIEW = "Overview"  # name of the text between the title and the first section


class PolicyError(Exception):
    """A policy folder or file that cannot be loaded, or an unusable search."""


@dataclass(frozen=True)
class Chunk:
    section: str
    section_slug: str
    content: str


@dataclass(frozen=True)
class PolicyHit:
    citation: str
    document: str
    title: str
    section: str
    rank: float
    snippet: str
    content: str


def slugify(text: str) -> str:
    """ "Order quantities" -> "order-quantities"."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _split_long(text: str) -> list[str]:
    """Split text at blank lines into pieces of at most MAX_CHUNK_CHARS (where possible)."""
    pieces, current = [], ""
    for paragraph in text.split("\n\n"):
        candidate = f"{current}\n\n{paragraph}" if current else paragraph
        if current and len(candidate) > MAX_CHUNK_CHARS:
            pieces.append(current)
            current = paragraph
        else:
            current = candidate
    return [*pieces, current] if current else pieces


def parse_policy(text: str) -> tuple[str, list[Chunk]]:
    """Title and chunks of one Markdown policy. Raises PolicyError without a `# ` title."""
    lines = text.replace("\r\n", "\n").split("\n")
    if not lines or not lines[0].startswith("# "):
        raise PolicyError("a policy must start with a '# Title' line")
    title = lines[0][2:].strip()

    sections: list[tuple[str, list[str]]] = [(OVERVIEW, [])]
    for line in lines[1:]:
        if line.startswith("## "):
            sections.append((line[3:].strip(), []))
        else:
            sections[-1][1].append(line)

    headings = [heading for heading, _ in sections[1:]]
    if len({slugify(heading) for heading in headings}) != len(headings):
        raise PolicyError("two sections have the same name")

    chunks = []
    for heading, body in sections:
        content = "\n".join(body).strip()
        if not content:
            continue
        for piece in _split_long(content):
            chunks.append(Chunk(heading, slugify(heading), piece.strip()))
    return title, chunks


def sync_policies(session: Session, folder: Path = DEFAULT_FOLDER) -> dict[str, list[str]]:
    """Make the table match the folder, in the caller's transaction.

    Unchanged documents (same SHA-256) are left alone, changed ones are replaced,
    and documents whose file was removed are deleted, so the copilot never cites
    a policy that no longer exists. Does not commit.
    """
    files = sorted(Path(folder).glob("*.md"))
    if not files:
        raise PolicyError(f"no .md policy files in {folder}")
    loaded = dict(
        session.execute(
            select(DocumentChunk.document, func.min(DocumentChunk.document_sha256)).group_by(
                DocumentChunk.document
            )
        ).all()
    )

    result: dict[str, list[str]] = {"added": [], "updated": [], "unchanged": [], "removed": []}
    for path in files:
        name = path.stem
        if not DOCUMENT_NAME.match(name):
            raise PolicyError(f"{path.name}: use lower-case letters, digits and dashes")
        raw = path.read_bytes()
        checksum = hashlib.sha256(raw).hexdigest()
        if loaded.get(name) == checksum:
            result["unchanged"].append(name)
            continue
        try:
            title, chunks = parse_policy(raw.decode("utf-8"))
        except PolicyError as error:
            raise PolicyError(f"{path.name}: {error}") from error
        session.execute(delete(DocumentChunk).where(DocumentChunk.document == name))
        session.add_all(
            DocumentChunk(
                document=name,
                title=title,
                section=chunk.section,
                section_slug=chunk.section_slug,
                chunk_index=index,
                content=chunk.content,
                document_sha256=checksum,
            )
            for index, chunk in enumerate(chunks)
        )
        result["updated" if name in loaded else "added"].append(name)

    for name in sorted(set(loaded) - {path.stem for path in files}):
        session.execute(delete(DocumentChunk).where(DocumentChunk.document == name))
        result["removed"].append(name)
    session.flush()
    return result


def citation_for(chunk: DocumentChunk) -> str:
    return f"policy:{chunk.document}#{chunk.section_slug}"


def search_policies(session: Session, query: str, limit: int = 5) -> list[PolicyHit]:
    """Best-matching policy sections for a question, best first. [] if nothing matches."""
    query = query.strip()
    if not query or len(query) > MAX_QUERY_CHARS:
        raise PolicyError(f"the search text must be 1 to {MAX_QUERY_CHARS} characters")

    searchable = func.to_tsvector(
        "english", DocumentChunk.title + " " + DocumentChunk.section + " " + DocumentChunk.content
    )
    # plainto_tsquery stems the words and drops stop words, joining them with AND
    # ("&"). Swapping in OR ("|") lets any word match; ts_rank then puts chunks
    # with more matching words first. The input never becomes SQL: it is a bound
    # parameter, and plainto_tsquery treats it as plain text.
    any_word = cast(
        func.replace(cast(func.plainto_tsquery("english", query), Text), "&", "|"), TSQUERY
    )
    rank = func.ts_rank(searchable, any_word)
    snippet = func.ts_headline(
        "english", DocumentChunk.content, any_word, "MaxWords=35, MinWords=15, MaxFragments=1"
    )
    rows = session.execute(
        select(DocumentChunk, rank, snippet)
        .where(searchable.op("@@")(any_word))
        .order_by(rank.desc(), DocumentChunk.document, DocumentChunk.chunk_index)
        .limit(limit)
    ).all()
    return [
        PolicyHit(
            citation=citation_for(chunk),
            document=chunk.document,
            title=chunk.title,
            section=chunk.section,
            rank=round(float(score), 4),
            snippet=text,
            content=chunk.content,
        )
        for chunk, score, text in rows
    ]
