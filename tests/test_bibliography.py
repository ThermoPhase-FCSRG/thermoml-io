"""Tests for deterministic APA, BibTeX, and authors-year metadata."""

from __future__ import annotations

from thermoml_io import Citation, publication_citation


def test_publication_citation_uses_reported_metadata_without_network() -> None:
    citation = Citation(
        authors=("Example, A.[Alice]", "Tester, B."),
        title="A synthetic thermodynamic study",
        publication_name="Journal of Synthetic Data",
        year=2026,
        volume="7",
        pages="10-20",
        doi="https://doi.org/10.0000/EXAMPLE",
        url="https://example.invalid/article",
    )
    formatted = publication_citation(citation)
    assert formatted.authors_year == "Example & Tester (2026)"
    assert formatted.apa.startswith("Example, A. & Tester, B. (2026).")
    assert "Journal of Synthetic Data" in formatted.apa
    assert formatted.apa.endswith("https://doi.org/10.0000/example.")
    assert formatted.bibtex.startswith("@article{example2026_")
    assert "author = {Example, Alice and Tester, B.}" in formatted.bibtex
    assert "doi = {10.0000/example}" in formatted.bibtex
    assert "url = {https://example.invalid/article}" in formatted.bibtex


def test_authors_year_fallbacks_and_bibtex_escaping() -> None:
    corporate = publication_citation(
        Citation(authors=("Thermodynamics Consortium",), title="A & B", year=None)
    )
    assert corporate.authors_year == "Consortium (n.d.)"
    assert "title = {A \\& B}" in corporate.bibtex

    unknown = publication_citation(Citation(title="Untitled metadata", year=2001))
    assert unknown.authors_year == "Unknown author (2001)"
    assert unknown.bibtex.startswith("@misc{unknown2001_")

    group = publication_citation(Citation(authors=("One, A.", "Two, B.", "Three, C."), year=1999))
    assert group.authors_year == "One et al. (1999)"
