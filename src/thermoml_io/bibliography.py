"""Deterministic citation views derived from reported ThermoML metadata."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

from citationlib.styles import APAStyle
from citationlib.styles import Author as CitationLibAuthor
from citationlib.styles import Citation as CitationLibCitation

from .models import Citation


@dataclass(frozen=True, slots=True)
class PublicationCitation:
    """Reusable publication strings generated without network enrichment."""

    authors_year: str
    apa: str
    bibtex: str


def _author(value: str) -> CitationLibAuthor:
    raw = value.strip()
    if "," in raw:
        last_name, reported_given = (part.strip() for part in raw.split(",", 1))
        expanded = re.findall(r"\[([^]]+)]", reported_given)
        first_name = expanded[-1].strip() if expanded else reported_given.split("[")[0]
    else:
        parts = raw.split()
        first_name = " ".join(parts[:-1]) if len(parts) > 1 else "?"
        last_name = parts[-1] if parts else "Unknown"
    return CitationLibAuthor(
        first_name=first_name.strip() or "?",
        last_name=last_name.strip() or "Unknown",
    )


def _authors_year(authors: tuple[CitationLibAuthor, ...], year: int | None) -> str:
    date = str(year) if year is not None else "n.d."
    if not authors:
        return f"Unknown author ({date})"
    if len(authors) == 1:
        names = authors[0].last_name
    elif len(authors) == 2:
        names = f"{authors[0].last_name} & {authors[1].last_name}"
    else:
        names = f"{authors[0].last_name} et al."
    return f"{names} ({date})"


def _plain_apa(value: str) -> str:
    return value.replace("<i>", "").replace("</i>", "").replace(".. (", ". (")


def _bibtex_value(value: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "{": r"\{",
        "}": r"\}",
        "%": r"\%",
        "&": r"\&",
    }
    return "".join(replacements.get(character, character) for character in value)


def _citation_key(citation: Citation, authors: tuple[CitationLibAuthor, ...]) -> str:
    lead = authors[0].last_name if authors else "unknown"
    normalized = unicodedata.normalize("NFKD", lead).encode("ascii", "ignore").decode()
    lead_key = "".join(character for character in normalized.casefold() if character.isalnum())
    year = str(citation.year) if citation.year is not None else "nd"
    identity = citation.normalized_doi or citation.title or citation.url or repr(citation)
    suffix = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:8]
    return f"{lead_key or 'unknown'}{year}_{suffix}"


def _bibtex(citation: Citation, authors: tuple[CitationLibAuthor, ...]) -> str:
    author_field = " and ".join(f"{author.last_name}, {author.first_name}" for author in authors)
    fields = [
        ("author", author_field or None),
        ("title", citation.title),
        ("journal", citation.publication_name),
        ("year", str(citation.year) if citation.year is not None else None),
        ("volume", citation.volume),
        ("pages", citation.pages),
        ("doi", citation.normalized_doi),
        ("url", citation.url),
    ]
    selected = [(name, value) for name, value in fields if value]
    entry_type = "article" if citation.publication_name else "misc"
    lines = [f"@{entry_type}{{{_citation_key(citation, authors)},"]
    for index, (name, value) in enumerate(selected):
        comma = "," if index < len(selected) - 1 else ""
        lines.append(f"  {name} = {{{_bibtex_value(value)}}}{comma}")
    lines.append("}")
    return "\n".join(lines)


@lru_cache(maxsize=4096)
def publication_citation(citation: Citation) -> PublicationCitation:
    """Format reported citation metadata without contacting external services.

    The pinned CitationLib APA formatter receives an in-memory citation built
    from ThermoML. BibTeX is serialized directly from the same values because
    CitationLib's public API otherwise performs live DOI metadata retrieval.
    """
    authors = tuple(_author(value) for value in citation.authors if value.strip())
    library_citation = CitationLibCitation(
        authors=list(authors),
        title=citation.title or "Untitled publication",
        year=citation.year,
        journal=citation.publication_name,
        volume=citation.volume,
        pages=citation.pages,
        doi=citation.normalized_doi,
        url=citation.url,
    )
    return PublicationCitation(
        authors_year=_authors_year(authors, citation.year),
        apa=_plain_apa(APAStyle().format_citation(library_citation)),
        bibtex=_bibtex(citation, authors),
    )
