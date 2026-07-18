"""Explains, for a given EUtils/EDirect request, what the equivalent
NCBI Datasets API v2 call would be - if one exists. This module only
describes equivalences; it never executes or forwards any request.

Coverage note: NCBI Datasets API v2 only covers genome assemblies,
gene records, taxonomy, and virus data. EUtils/EDirect covers the
whole Entrez ecosystem (PubMed, arbitrary Nucleotide/Protein fetches,
SRA, BioProject, free-text boolean queries, etc.). Requests outside
Datasets' scope have no translation - the result explains why and
shows the original EUtils/EDirect call for reference.
"""
from urllib.parse import urlencode, quote

from .model import ParsedRequest, TranslationResult
from .parser import extract_field_tags, has_unsupported_boolean

DATASETS_REST_BASE = "https://api.ncbi.nlm.nih.gov/datasets/v2"
EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

ACCESSION_RE_PREFIXES = ("GCF_", "GCA_")

# EUtils rettype/format values that imply the caller wants actual sequence
# or annotation files, not just metadata.
DOWNLOAD_RETTYPES = {"fasta", "gb", "gbwithparts", "gff3", "gbff"}


def rebuild_eutils_url(req: ParsedRequest) -> str:
    """Reconstruct a canonical EUtils URL from a ParsedRequest, whether
    the original input was a URL or an EDirect pipeline. Shown for
    reference when no Datasets translation exists - not something this
    tool calls or executes."""
    params = {}
    extra = dict(req.extra)

    if req.tool == "elink":
        # req.db is always normalized to the source db (see parser.py);
        # real EUtils elink wants that as dbfrom=, with db= as the target.
        if req.db:
            params["dbfrom"] = req.db
        target = extra.pop("target", None)
        if target:
            params["db"] = target
    elif req.db:
        params["db"] = req.db

    if req.term:
        params["term"] = req.term
    if req.ids:
        params["id"] = req.ids
    if req.rettype:
        params["rettype"] = req.rettype
    params.update(extra)

    tool = req.tool if req.tool in {"esearch", "efetch", "esummary", "elink", "epost", "einfo"} else "esearch"
    return f"{EUTILS_BASE}/{tool}.fcgi?{urlencode(params)}"


def _wants_download(req: ParsedRequest) -> bool:
    return (req.rettype or "").lower() in DOWNLOAD_RETTYPES


def _translate_gene(req: ParsedRequest) -> TranslationResult:
    tags = extract_field_tags(req.term or "")
    if req.term and has_unsupported_boolean(req.term):
        return TranslationResult(
            supported=False,
            reason="Gene query uses OR/NOT/grouping, which Datasets' structured "
                    "gene lookup can't express.",
            eutils_reference=rebuild_eutils_url(req),
        )

    gene_id = req.ids or tags.get("uid")
    symbol = tags.get("gene") or tags.get("sym")
    organism = tags.get("orgn")

    if gene_id:
        cli = f"datasets summary gene gene-id {gene_id}"
        rest = f"{DATASETS_REST_BASE}/gene/id/{quote(str(gene_id))}"
        if _wants_download(req):
            cli = f"datasets download gene gene-id {gene_id}"
        return TranslationResult(True, "Gene lookup by NCBI Gene ID.", cli, rest)

    if symbol:
        if organism:
            cli = f'datasets summary gene symbol {symbol} --taxon "{organism}"'
            rest = f"{DATASETS_REST_BASE}/gene/symbol/{quote(symbol)}/taxon/{quote(organism)}"
        else:
            cli = f"datasets summary gene symbol {symbol}"
            rest = f"{DATASETS_REST_BASE}/gene/symbol/{quote(symbol)}"
        if _wants_download(req):
            cli = cli.replace("summary", "download", 1)
        return TranslationResult(True, "Gene lookup by symbol (+ taxon).", cli, rest)

    return TranslationResult(
        supported=False,
        reason="No gene ID or [gene]/[sym] field tag found - Datasets needs a "
               "symbol or gene ID, not free-text search.",
        eutils_reference=rebuild_eutils_url(req),
    )


def _translate_assembly(req: ParsedRequest) -> TranslationResult:
    tags = extract_field_tags(req.term or "")
    if req.term and has_unsupported_boolean(req.term):
        return TranslationResult(
            supported=False,
            reason="Assembly query uses OR/NOT/grouping, unsupported by Datasets' "
                   "structured genome lookup.",
            eutils_reference=rebuild_eutils_url(req),
        )

    accession = req.ids if (req.ids or "").startswith(ACCESSION_RE_PREFIXES) else None
    organism = tags.get("orgn")

    if accession:
        cli = f"datasets summary genome accession {accession}"
        rest = f"{DATASETS_REST_BASE}/genome/accession/{quote(accession)}"
        if _wants_download(req):
            cli = f"datasets download genome accession {accession}"
        return TranslationResult(True, "Genome lookup by assembly accession.", cli, rest)

    if organism:
        cli = f'datasets summary genome taxon "{organism}"'
        rest = f"{DATASETS_REST_BASE}/genome/taxon/{quote(organism)}"
        if "latest" in (req.term or "").lower():
            cli += " --assembly-version latest"
        if _wants_download(req):
            cli = cli.replace("summary", "download", 1)
        return TranslationResult(True, "Genome lookup by organism/taxon.", cli, rest)

    return TranslationResult(
        supported=False,
        reason="No assembly accession (GCF_/GCA_) or [orgn] tag found.",
        eutils_reference=rebuild_eutils_url(req),
    )


def _translate_taxonomy(req: ParsedRequest) -> TranslationResult:
    taxon = req.ids or (req.term.strip() if req.term else None)
    if not taxon:
        return TranslationResult(
            supported=False,
            reason="No taxonomy ID or name found in request.",
            eutils_reference=rebuild_eutils_url(req),
        )
    if req.term and has_unsupported_boolean(req.term):
        return TranslationResult(
            supported=False,
            reason="Taxonomy query uses OR/NOT/grouping, unsupported by Datasets.",
            eutils_reference=rebuild_eutils_url(req),
        )
    cli = f'datasets summary taxonomy taxon "{taxon}"'
    rest = f"{DATASETS_REST_BASE}/taxonomy/taxon/{quote(str(taxon))}"
    return TranslationResult(True, "Taxonomy lookup by ID or name.", cli, rest)


DB_TRANSLATORS = {
    "gene": _translate_gene,
    "assembly": _translate_assembly,
    "taxonomy": _translate_taxonomy,
}


# --- elink: many cross-database links are actually fields already embedded
# in a Datasets metadata report, not a distinct "link" operation. Where that's
# true, we replace the elink call with a single report call plus a pointer to
# the field that holds the linked accession(s), rather than a two-step
# esearch+efetch/elink dance.
#
# Field mnemonics below are given for `dataformat`, NOT raw JSON dot-paths -
# the raw JSON schema has drifted across Datasets API versions (nesting and
# casing both), but dataformat's --fields mnemonics are the documented,
# version-stable way to pull a specific value out of a report. Treat the
# mnemonics here as best-effort; run `dataformat tsv <report> --help` to
# confirm the exact name if a pipeline depends on it.

def _link_seq_to_gene(req: ParsedRequest) -> TranslationResult:
    """nuccore/protein -> gene: Datasets can resolve a RefSeq nucleotide or
    protein accession directly to its gene record."""
    accession = req.ids
    if not accession:
        return TranslationResult(
            False,
            "Need a specific RefSeq nucleotide/protein accession as -id to "
            "resolve to a gene record.",
            eutils_reference=rebuild_eutils_url(req),
        )
    return TranslationResult(
        True,
        "Datasets resolves a RefSeq nucleotide/protein accession straight to "
        "its gene record - no separate link step needed.",
        datasets_cli=f"datasets summary gene accession {accession}",
        datasets_rest=f"{DATASETS_REST_BASE}/gene/accession/{quote(accession)}",
    )


def _link_gene_to_seq(req: ParsedRequest) -> TranslationResult:
    """gene -> nuccore/protein: the gene product report lists every
    transcript/protein accession linked to the gene."""
    tags = extract_field_tags(req.term or "")
    gene_id = req.ids or tags.get("uid")
    symbol = tags.get("gene") or tags.get("sym")
    if not (gene_id or symbol):
        return TranslationResult(
            False,
            "Need a Gene ID or symbol to look up linked transcripts/proteins.",
            eutils_reference=rebuild_eutils_url(req),
        )
    locator = f"gene-id {gene_id}" if gene_id else f"symbol {symbol}"
    cli = (f"datasets summary gene {locator} --report product --as-json-lines | "
           f"dataformat tsv gene-product --fields symbol,gene-id,"
           f"transcript-accession,transcript-protein-accession")
    rest = f"{DATASETS_REST_BASE}/gene/{'id' if gene_id else 'symbol'}/{quote(str(gene_id or symbol))}"
    return TranslationResult(
        True,
        "The gene product report lists every linked transcript/protein "
        "accession - pull them out with dataformat instead of elink+efetch.",
        datasets_cli=cli,
        datasets_rest=rest,
        field_hint="REST response's product/transcript records include the "
                    "linked nucleotide + protein accessions directly.",
    )


def _link_assembly_to_field(cli_field: str, rest_note: str):
    """Factory for assembly-> {bioproject, biosample, taxonomy} links: all
    three live as fields inside the standard genome assembly report."""
    def handler(req: ParsedRequest) -> TranslationResult:
        accession = req.ids
        tags = extract_field_tags(req.term or "")
        organism = tags.get("orgn")
        if accession:
            locator, rest = f"accession {accession}", f"{DATASETS_REST_BASE}/genome/accession/{quote(accession)}"
        elif organism:
            locator, rest = f'taxon "{organism}"', f"{DATASETS_REST_BASE}/genome/taxon/{quote(organism)}"
        else:
            return TranslationResult(
                False,
                "Need an assembly accession or organism to look up.",
                eutils_reference=rebuild_eutils_url(req),
            )
        cli = (f"datasets summary genome {locator} --as-json-lines | "
               f"dataformat tsv genome --fields assminfo-accession,{cli_field}")
        return TranslationResult(
            True,
            f"{rest_note} is already a field in the standard genome report.",
            datasets_cli=cli,
            datasets_rest=rest,
            field_hint=f"Look for the {cli_field.replace('-', ' ')} field in the report.",
        )
    return handler


def _link_assembly_to_seq(req: ParsedRequest) -> TranslationResult:
    """assembly -> nuccore: the genome *sequence* report enumerates every
    chromosome/scaffold/contig accession that makes up the assembly."""
    accession = req.ids
    if not accession:
        return TranslationResult(
            False,
            "Need an assembly accession to list its component sequences.",
            eutils_reference=rebuild_eutils_url(req),
        )
    cli = (f"datasets summary genome accession {accession} --report sequence "
           f"--as-json-lines | dataformat tsv genome-seq --fields accession,refseq-seq-acc")
    return TranslationResult(
        True,
        "The genome sequence report enumerates every nucleotide accession in "
        "the assembly - this is the assembly->nuccore link, structurally.",
        datasets_cli=cli,
        datasets_rest=f"{DATASETS_REST_BASE}/genome/accession/{quote(accession)}/sequence_reports",
        field_hint="Each entry is one chromosome/scaffold/contig accession.",
    )


def _link_taxonomy_to_assembly(req: ParsedRequest) -> TranslationResult:
    """taxonomy -> assembly: not literally a field extraction (this one really
    is a search, not a link), but it's the direct structural equivalent -
    every assembly for a taxon in one call."""
    taxon = req.ids or (req.term.strip() if req.term else None)
    if not taxon:
        return TranslationResult(
            False,
            "Need a taxonomy ID or name to list its assemblies.",
            eutils_reference=rebuild_eutils_url(req),
        )
    return TranslationResult(
        True,
        "Lists every genome assembly for this taxon in one call - the "
        "structural equivalent of a taxonomy->assembly elink.",
        datasets_cli=f'datasets summary genome taxon "{taxon}"',
        datasets_rest=f"{DATASETS_REST_BASE}/genome/taxon/{quote(str(taxon))}",
    )


ELINK_MAP = {
    ("nuccore", "gene"): _link_seq_to_gene,
    ("protein", "gene"): _link_seq_to_gene,
    ("gene", "nuccore"): _link_gene_to_seq,
    ("gene", "protein"): _link_gene_to_seq,
    ("assembly", "bioproject"): _link_assembly_to_field(
        "assminfo-bioproject-accession", "The linked BioProject accession"),
    ("assembly", "biosample"): _link_assembly_to_field(
        "assminfo-biosample-accession", "The linked BioSample accession"),
    ("assembly", "taxonomy"): _link_assembly_to_field(
        "tax-id", "The linked taxonomy ID"),
    ("assembly", "nuccore"): _link_assembly_to_seq,
    ("taxonomy", "assembly"): _link_taxonomy_to_assembly,
}


def _translate_elink(req: ParsedRequest) -> TranslationResult:
    source_db = (req.db or "").lower()
    target_db = (req.extra.get("target") or "").lower()
    handler = ELINK_MAP.get((source_db, target_db))
    if handler is None:
        return TranslationResult(
            False,
            f"No Datasets-report equivalent known for {source_db or '?'}->"
            f"{target_db or '?'}; this link needs real elink.",
            eutils_reference=rebuild_eutils_url(req),
        )
    return handler(req)


def translate(req: ParsedRequest) -> TranslationResult:
    if req.tool == "elink":
        return _translate_elink(req)
    if req.tool in ("epost", "einfo"):
        return TranslationResult(
            False,
            f"{req.tool} is an Entrez history/metadata operation with no Datasets "
            "equivalent.",
            eutils_reference=rebuild_eutils_url(req),
        )

    db = (req.db or "").lower()
    handler = DB_TRANSLATORS.get(db)
    if handler is None:
        return TranslationResult(
            False,
            f"db={db or '?'} is outside Datasets API's scope (it covers gene, "
            "assembly/genome, and taxonomy only).",
            eutils_reference=rebuild_eutils_url(req),
        )
    return handler(req)
