"""Parsers that turn either a raw EUtils HTTP call or an EDirect shell
pipeline into a single normalized ParsedRequest.

Two input shapes are supported:

1. Raw EUtils URL, e.g.:
   https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=gene&term=BRCA1[gene]+AND+human[orgn]

2. EDirect command-line pipeline, e.g.:
   esearch -db gene -query "BRCA1[gene] AND human[orgn]" | efetch -format docsum
   efetch -db assembly -id GCF_000001405.40 -format docsum
"""
import re
import shlex
from urllib.parse import urlparse, parse_qs

from .model import ParsedRequest

EUTILS_TOOLS = {"esearch", "efetch", "esummary", "elink", "epost", "einfo"}


def is_url(text: str) -> bool:
    return text.strip().lower().startswith(("http://", "https://"))


def parse_eutils_url(url: str) -> ParsedRequest:
    parsed = urlparse(url)
    fname = parsed.path.rsplit("/", 1)[-1]  # e.g. esearch.fcgi
    tool = fname.replace(".fcgi", "").lower()
    if tool not in EUTILS_TOOLS:
        tool = tool or "unknown"

    q = {k: v[0] for k, v in parse_qs(parsed.query).items()}

    if tool == "elink":
        # EUtils elink uses dbfrom=<source>, db=<target> - the reverse of every
        # other EUtils tool, where db= is simply "the database". Normalize so
        # ParsedRequest.db is always the source, matching EDirect's -db/-target.
        source_db = q.pop("dbfrom", None)
        target_db = q.pop("db", None)
        if target_db:
            q["target"] = target_db
        db = source_db
    else:
        db = q.pop("db", None)

    return ParsedRequest(
        tool=tool,
        db=db,
        term=q.pop("term", None),
        ids=q.pop("id", None),
        rettype=q.pop("rettype", None),
        extra=q,
        raw=url,
    )


def parse_edirect_pipeline(command: str) -> ParsedRequest:
    """EDirect pipelines chain stages with `|`. We fold every stage's
    flags into one logical request, since Datasets mapping only cares
    about the effective db/query/id/format, not the pipeline mechanics."""
    stages = [s.strip() for s in command.split("|") if s.strip()]

    tool = None
    db = None
    term = None
    ids = None
    rettype = None
    extra = {}

    for stage in stages:
        tokens = shlex.split(stage)
        if not tokens:
            continue
        stage_tool = tokens[0].lower()
        if stage_tool in EUTILS_TOOLS and tool is None:
            # first recognized EUtils-style stage sets the "primary" tool
            tool = stage_tool
        elif tool is None:
            tool = stage_tool  # e.g. xtract, unrecognized - keep for passthrough clarity

        it = iter(tokens[1:])
        for flag in it:
            if not flag.startswith("-"):
                continue
            key = flag.lstrip("-")
            try:
                val = next(it)
            except StopIteration:
                val = ""
            if key == "db":
                db = db or val
            elif key in ("query", "term"):
                term = term or val
            elif key == "id":
                ids = ids or val
            elif key in ("format", "rettype"):
                rettype = rettype or val
            else:
                extra.setdefault(key, val)

    return ParsedRequest(
        tool=tool or "unknown",
        db=db,
        term=term,
        ids=ids,
        rettype=rettype,
        extra=extra,
        raw=command,
    )


def parse(input_text: str) -> ParsedRequest:
    """Entry point: accepts either a raw EUtils URL or an EDirect pipeline
    string and returns a normalized ParsedRequest."""
    input_text = input_text.strip()
    if is_url(input_text):
        return parse_eutils_url(input_text)
    return parse_edirect_pipeline(input_text)


# --- helpers for pulling EUtils field-tagged terms out of a query string ---

# A single ANDed clause like `Homo sapiens[orgn]` or `"BRCA1"[gene]` - the
# whole clause up to the trailing [tag], quotes optional either way. Real
# Entrez field tags aren't always single words - db=assembly uses
# `[Assembly Level]` and `[RefSeq Category]` - so the tag itself may
# contain spaces too.
CLAUSE_TAG_RE = re.compile(r'^\s*"?(.*?)"?\s*\[([\w ]+)\]\s*$')
AND_SPLIT_RE = re.compile(r'\bAND\b', re.IGNORECASE)


def extract_field_tags(term: str) -> dict:
    """Given a term/query string like 'Homo sapiens[orgn] AND latest[filter]',
    return {'orgn': 'Homo sapiens', 'filter': 'latest'}. Splits on AND (the
    only boolean operator Datasets' structured lookups can express) and
    reads each clause's full value up to its trailing [tag], so multi-word
    values without inner quoting are captured correctly. Clauses without a
    recognizable [tag] are silently skipped (caller checks for completeness,
    not exhaustiveness).

    Multi-word tags (e.g. `[Assembly Level]`, `[RefSeq Category]`) are
    normalized by lowercasing and stripping internal spaces, so callers look
    them up as 'assemblylevel', 'refseqcategory', etc."""
    if not term:
        return {}
    tags = {}
    for clause in AND_SPLIT_RE.split(term):
        match = CLAUSE_TAG_RE.match(clause.strip())
        if match:
            value = match.group(1).strip()
            field_name = re.sub(r'\s+', '', match.group(2).strip().lower())
            tags[field_name] = value
    return tags


def has_unsupported_boolean(term: str) -> bool:
    """Detect OR / NOT logic, or parenthetical grouping, which the
    Datasets API's structured lookups have no equivalent for."""
    if not term:
        return False
    return bool(re.search(r'\bOR\b|\bNOT\b|[()]', term, re.IGNORECASE))
