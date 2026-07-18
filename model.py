"""Data model shared across the parser, classifier, and translator."""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ParsedRequest:
    """Normalized representation of an EUtils/EDirect call, regardless of
    whether it arrived as a raw HTTP URL or an EDirect shell pipeline."""

    tool: str                      # esearch, efetch, esummary, elink, epost, einfo
    db: Optional[str] = None       # e.g. gene, assembly, taxonomy, pubmed, nuccore
    term: Optional[str] = None     # esearch -query / term=
    ids: Optional[str] = None      # efetch/esummary -id / id=
    rettype: Optional[str] = None  # efetch -format / rettype=
    extra: dict = field(default_factory=dict)  # anything else we captured
    raw: str = ""                  # original input, verbatim


@dataclass
class TranslationResult:
    """The result of explaining one EUtils/EDirect request in Datasets
    terms. This is a pure explanation - nothing in this library calls
    EUtils, Datasets, or any other network endpoint."""

    supported: bool
    reason: str
    datasets_cli: Optional[str] = None
    datasets_rest: Optional[str] = None
    eutils_reference: Optional[str] = None  # the equivalent EUtils/EDirect
                                             # call, shown for reference when
                                             # no Datasets translation exists
    field_hint: Optional[str] = None  # where in the report the "linked" data lives,
                                       # for elink-style translations that resolve to
                                       # a field inside a report rather than a call
                                       # that returns only the linked IDs
