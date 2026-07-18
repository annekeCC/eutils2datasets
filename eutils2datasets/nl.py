"""Lets a person ask, in plain language, how to get some data from NCBI,
instead of writing an EUtils/EDirect call by hand.

This is a lightweight heuristic parser, not real NLU: it looks for
recognizable entities (accessions, gene symbols, taxonomy IDs, organism
names) and a handful of intent-indicating phrases, builds the same
ParsedRequest the EUtils/EDirect path would produce, and then runs it
through the exact same translator. That reuse matters: the plain-language
mode can't give a different (and possibly wrong) answer than the
EUtils-call mode would for the equivalent request.

Because it's heuristic, coverage is intentionally narrow: gene lookups,
genome/assembly lookups, taxonomy lookups, the elink-style relationships
from translator.ELINK_MAP, ortholog-set questions, and WP_ accession
flanking-sequence questions. Anything else returns a clear "couldn't
confidently parse this" result rather than a guess dressed up as
confidence.

Orthologs and flanking sequence are handled specially: unlike every other
pattern here, there's no real EUtils/EDirect syntax to fall back to for
them (the legacy ortholog elink is dead, and EDirect has no flanking-
sequence concept at all), so these two are --ask-only - see
translator._link_gene_ortholog and translator._link_seq_to_gene.
"""
import re

from .model import ParsedRequest, TranslationResult
from .translator import translate as translate_request

ACCESSION_RE = re.compile(
    r'\b(GCF_\d+\.\d+|GCA_\d+\.\d+|[NX][MRPCGTW]_\d+(?:\.\d+)?)\b', re.IGNORECASE
)
WP_ACCESSION_RE = re.compile(r'\bWP_\d+(?:\.\d+)?\b', re.IGNORECASE)
TAXID_CONTEXT_RE = re.compile(r'\btax(?:onomy)?[\s_-]*id\s*(\d+)\b', re.IGNORECASE)
GENE_ID_CONTEXT_RE = re.compile(r'\bgene\s*id\s*(\d+)\b', re.IGNORECASE)
BARE_GENE_SYMBOL_RE = re.compile(r'\b([A-Z][A-Z0-9]{1,9})\b')
ORTHOLOG_RE = re.compile(r'\bortholog', re.IGNORECASE)
ORTHOLOG_TAXA_RE = re.compile(r'\b(?:in|across|among)\s+([a-zA-Z][\w \-]*?)\s*[.?!]*$', re.IGNORECASE)
FLANK_RE = re.compile(r'\bflank', re.IGNORECASE)
FLANK_BP_RE = re.compile(r'(\d+)\s*(?:bp|base\s*pairs?)\b', re.IGNORECASE)

# Common names -> the form Datasets/EUtils organism lookups expect. Not
# exhaustive - anything not here just gets passed through as typed, which
# works fine for proper scientific names the person already typed correctly.
COMMON_ORGANISMS = {
    "human": "human", "humans": "human", "people": "human",
    "mouse": "mouse", "mice": "mouse",
    "rat": "rat", "rats": "rat",
    "zebrafish": "zebrafish",
    "yeast": "yeast",
    "fly": "fruit fly", "fruit fly": "fruit fly", "drosophila": "fruit fly",
    "e. coli": "E. coli", "ecoli": "E. coli",
}

# (regex, (source_db, target_db)) - phrases that indicate an elink-style
# relationship. Checked before the plain single-db intents below, since
# "what gene is this protein from" mentions both "gene" and "protein".
LINK_INTENTS = [
    (re.compile(r'\bwhat gene\b|\bwhich gene\b|\bgene (?:is|for) this\b', re.I), ("nuccore", "gene")),
    (re.compile(r'\btranscripts?\b.*\bgene\b|\bproteins?\b.*\bgene\b|\bgene\b.*\btranscripts?\b', re.I), ("gene", "nuccore")),
    (re.compile(r'\bbioproject\b', re.I), ("assembly", "bioproject")),
    (re.compile(r'\bbiosample\b', re.I), ("assembly", "biosample")),
    (re.compile(r'\bchromosomes?\b|\bscaffolds?\b|\bcontigs?\b|\bsequences? (?:in|of|for|making up) (?:this|the) (?:assembly|genome)\b', re.I), ("assembly", "nuccore")),
    (re.compile(r'\btaxonomy\b.*\b(?:assembly|genome)\b|\b(?:assembly|genome)\b.*\btaxonomy\b|\bwhat species\b|\bwhat organism\b', re.I), ("assembly", "taxonomy")),
    (re.compile(r'\bassemblies\b.*\b(?:species|taxon|organism)\b|\bgenomes? (?:for|of) this species\b', re.I), ("taxonomy", "assembly")),
]

# (regex, db) - single-database intents, checked after link intents.
DB_INTENTS = [
    (re.compile(r'\bgene\b', re.I), "gene"),
    (re.compile(r'\bgenome\b|\bassembly\b|\bassemblies\b', re.I), "assembly"),
    (re.compile(r'\btaxonomy\b|\bspecies\b|\borganism\b|\btaxon\b', re.I), "taxonomy"),
]


def _find_organism(question: str) -> str:
    lowered = question.lower()
    for name, normalized in COMMON_ORGANISMS.items():
        if re.search(rf'\b{re.escape(name)}\b', lowered):
            return normalized
    # Fallback: a capitalized two-word binomial, e.g. "Homo sapiens"
    match = re.search(r'\b([A-Z][a-z]+ [a-z]+)\b', question)
    return match.group(1) if match else None


def _find_gene_symbol(question: str) -> str:
    # Exclude common all-caps words that aren't gene symbols
    stoplist = {"NCBI", "DNA", "RNA", "API", "REST", "CLI", "URL", "ID", "US"}
    for match in BARE_GENE_SYMBOL_RE.finditer(question):
        if match.group(1) not in stoplist:
            return match.group(1)
    return None


def interpret(question: str) -> TranslationResult:
    """Parse a plain-language question and return the same TranslationResult
    shape the EUtils/EDirect translator produces, so callers don't need to
    handle two different response shapes."""
    accession_match = ACCESSION_RE.search(question)
    taxid_match = TAXID_CONTEXT_RE.search(question)
    gene_id_match = GENE_ID_CONTEXT_RE.search(question)
    organism = _find_organism(question)
    symbol = _find_gene_symbol(question) if not accession_match else None

    # 0a. Flanking-sequence questions ("100 bp flanking sequence for
    # WP_003249567.1") - checked first since "flank" is an unambiguous
    # signal not shared with any other pattern here.
    if FLANK_RE.search(question):
        wp_match = WP_ACCESSION_RE.search(question)
        bp_match = FLANK_BP_RE.search(question)
        if wp_match and bp_match:
            req = ParsedRequest(
                tool="elink", db="protein",
                extra={"target": "gene", "flank_bp": bp_match.group(1)},
                ids=wp_match.group(0).upper(),
                raw=question,
            )
            return translate_request(req)
        return TranslationResult(
            False,
            "This sounds like a flanking-sequence request, but I need both a "
            "WP_ protein accession and a bp length to build it - e.g. '100 bp "
            "flanking sequence for WP_003249567.1'.",
        )

    # 0b. Ortholog-set questions ("orthologs of BRCA1 in mammals") - also
    # checked before the generic link/db intents below, since these mention
    # "gene" but need the dedicated ortholog handler, not a plain gene lookup.
    if ORTHOLOG_RE.search(question):
        taxa_match = ORTHOLOG_TAXA_RE.search(question)
        taxa = taxa_match.group(1).strip() if taxa_match else "all"
        extra = {"target": "gene", "name": "gene_gene_homolog", "ortholog_taxa": taxa}
        if gene_id_match:
            req = ParsedRequest(tool="elink", db="gene", extra=extra,
                                 ids=gene_id_match.group(1), raw=question)
            return translate_request(req)
        if symbol:
            req = ParsedRequest(tool="elink", db="gene", extra=extra,
                                 term=f"{symbol}[gene]", raw=question)
            return translate_request(req)
        return TranslationResult(
            False,
            "This sounds like an ortholog question, but I couldn't find a "
            "gene symbol or Gene ID in it - try including one, e.g. "
            "'orthologs of BRCA1 in mammals'.",
        )

    # 1. Check elink-style ("X for/from Y") relationship phrasing first.
    for pattern, (source_db, target_db) in LINK_INTENTS:
        if pattern.search(question):
            req = ParsedRequest(
                tool="elink", db=source_db, extra={"target": target_db},
                ids=(accession_match.group(1) if accession_match
                     else gene_id_match.group(1) if gene_id_match
                     else taxid_match.group(1) if taxid_match else None),
                term=organism,
                raw=question,
            )
            if req.ids or req.term:
                return translate_request(req)
            # matched the phrasing but found no entity to anchor it to
            return TranslationResult(
                False,
                f"This sounds like a {source_db}->{target_db} link, but I "
                "couldn't find an accession, ID, or organism name in the "
                "question to look it up with.",
            )

    # 2. Otherwise fall back to a plain single-database lookup.
    if accession_match:
        accession = accession_match.group(1).upper()
        db = "assembly" if accession.startswith(("GCF_", "GCA_")) else "gene"
        req = ParsedRequest(tool="efetch", db=db, ids=accession, raw=question)
        return translate_request(req)

    for pattern, db in DB_INTENTS:
        if pattern.search(question):
            if db == "gene":
                if gene_id_match:
                    req = ParsedRequest(tool="efetch", db="gene", ids=gene_id_match.group(1), raw=question)
                elif symbol:
                    term = f"{symbol}[gene]" + (f" AND {organism}[orgn]" if organism else "")
                    req = ParsedRequest(tool="esearch", db="gene", term=term, raw=question)
                else:
                    return TranslationResult(
                        False,
                        "This sounds like a gene question, but I couldn't find a "
                        "gene symbol or Gene ID in it - try including one, e.g. "
                        "'gene BRCA1 in human'.",
                    )
            elif db == "assembly":
                if organism:
                    term = f"{organism}[orgn]"
                    req = ParsedRequest(tool="esearch", db="assembly", term=term, raw=question)
                else:
                    return TranslationResult(
                        False,
                        "This sounds like a genome/assembly question, but I "
                        "couldn't find an organism name or accession - try "
                        "including one, e.g. 'genome for human'.",
                    )
            else:  # taxonomy
                taxon = taxid_match.group(1) if taxid_match else organism
                if taxon:
                    req = ParsedRequest(tool="esearch", db="taxonomy", term=taxon, raw=question)
                else:
                    return TranslationResult(
                        False,
                        "This sounds like a taxonomy question, but I couldn't "
                        "find a species name or taxonomy ID - try including "
                        "one, e.g. 'taxonomy id for mouse'.",
                    )
            return translate_request(req)

    return TranslationResult(
        False,
        "Couldn't confidently tell what kind of NCBI record you're after. "
        "Try mentioning 'gene', 'genome'/'assembly', or 'taxonomy', plus a "
        "symbol, accession, or organism name - e.g. 'find the BRCA1 gene in "
        "human' or 'genome assembly for GCF_000001405.40'.",
    )
