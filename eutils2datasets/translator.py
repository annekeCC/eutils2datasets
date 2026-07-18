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

# The REST API has no bare /genome/accession/{accession} or /genome/taxon/{taxon}
# endpoint - every genome lookup needs a report-type suffix. Verified against
# the real datasets.openapi.yaml (only .../dataset_report, .../download, etc.
# exist) and live: a bare URL 404s, the same URL + this suffix returns 200
# with real data.
GENOME_REPORT_SUFFIX = "/dataset_report"

ACCESSION_RE_PREFIXES = ("GCF_", "GCA_")

# EUtils rettype/format values that imply the caller wants actual sequence
# or annotation files, not just metadata.
DOWNLOAD_RETTYPES = {"fasta", "gb", "gbwithparts", "gff3", "gbff"}

# db=assembly's real EDirect field tag `[Assembly Level]` uses values like
# "complete genome" - Datasets' --assembly-level wants the bare level word.
# Confirmed real query: `("complete genome"[Assembly Level] OR "reference
# genome"[RefSeq Category])` (github.com/brinkmanlab/MicrobeDB).
ASSEMBLY_LEVEL_MAP = {
    "complete genome": "complete",
    "complete": "complete",
    "chromosome": "chromosome",
    "scaffold": "scaffold",
    "contig": "contig",
}
# The REST filters.assembly_level enum uses different spellings than the CLI
# flag - verified against datasets.openapi.yaml's v2reportsAssemblyLevel enum
# (chromosome, scaffold, contig, complete_genome) and confirmed live.
REST_ASSEMBLY_LEVEL_MAP = {
    "complete genome": "complete_genome",
    "complete": "complete_genome",
    "chromosome": "chromosome",
    "scaffold": "scaffold",
    "contig": "contig",
}


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
        field_hint = None
        if organism:
            cli = f'datasets summary gene symbol {symbol} --taxon "{organism}"'
            rest = f"{DATASETS_REST_BASE}/gene/symbol/{quote(symbol)}/taxon/{quote(organism)}"
        else:
            cli = f"datasets summary gene symbol {symbol}"
            # There's no bare /gene/symbol/{symbol} REST path - verified
            # against datasets.openapi.yaml (only .../taxon/{taxon} exists)
            # and live (404). The CLI doesn't require a taxon; REST does.
            rest = None
            field_hint = ("REST requires a taxon for symbol lookups "
                          "(/gene/symbol/{symbol}/taxon/{taxon}) - the CLI form "
                          "shown works without one.")
        if _wants_download(req):
            cli = cli.replace("summary", "download", 1)
        return TranslationResult(True, "Gene lookup by symbol (+ taxon).", cli, rest, field_hint=field_hint)

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
        # No bare /genome/accession/{accession} REST path exists - verified
        # against datasets.openapi.yaml and live (404 without this suffix,
        # 200 with it).
        rest = f"{DATASETS_REST_BASE}/genome/accession/{quote(accession)}{GENOME_REPORT_SUFFIX}"
        if _wants_download(req):
            cli = f"datasets download genome accession {accession}"
        return TranslationResult(True, "Genome lookup by assembly accession.", cli, rest)

    if organism:
        cli = f'datasets summary genome taxon "{organism}"'
        if "latest" in (req.term or "").lower():
            cli += " --assembly-version latest"

        # Real-world bulk/comparative-genomics EUtils queries filter db=assembly
        # searches with these field tags before looping esummary/efetch over
        # each hit one at a time. Datasets folds every filter into the same
        # single taxon call instead - see ASSEMBLY_LEVEL_MAP above and
        # translator.py's module docstring reference for confirmed real
        # query syntax. Both the CLI flags and REST query params below were
        # verified together live against a real filtered query.
        filters = []
        rest_params = {}
        level = tags.get("assemblylevel")
        if level and level.lower() in ASSEMBLY_LEVEL_MAP:
            filters.append(f"--assembly-level {ASSEMBLY_LEVEL_MAP[level.lower()]}")
            rest_params["filters.assembly_level"] = REST_ASSEMBLY_LEVEL_MAP[level.lower()]
        refseq_category = tags.get("refseqcategory", "")
        if "reference" in refseq_category.lower():
            filters.append("--reference")
            rest_params["filters.reference_only"] = "true"
        source_prop = (tags.get("prop") or tags.get("properties") or "").lower()
        if source_prop == "srcdb_refseq":
            filters.append("--assembly-source refseq")
            rest_params["filters.assembly_source"] = "refseq"
        if (tags.get("filter") or "").lower() == "type_material":
            filters.append("--from-type")
            rest_params["filters.is_type_material"] = "true"
        for flag in filters:
            cli += f" {flag}"

        if _wants_download(req):
            cli = cli.replace("summary", "download", 1)

        rest = f"{DATASETS_REST_BASE}/genome/taxon/{quote(organism)}{GENOME_REPORT_SUFFIX}"
        if rest_params:
            rest += f"?{urlencode(rest_params)}"

        reason = "Genome lookup by organism/taxon."
        if filters:
            reason = (
                "Genome lookup by organism/taxon, with every filter folded into "
                "one `datasets` call - this replaces what used to be an esearch "
                "query followed by a loop of esummary/efetch calls (or manual "
                "filtering of the result list) to apply the same criteria."
            )
        return TranslationResult(True, reason, cli, rest)

    return TranslationResult(
        supported=False,
        reason="No assembly accession (GCF_/GCA_) or [orgn] tag found.",
        eutils_reference=rebuild_eutils_url(req),
    )


def _translate_taxonomy(req: ParsedRequest) -> TranslationResult:
    # `[Subtree]` is a real Entrez field tag (e.g. `txid9606[Subtree]` or
    # `"Escherichia"[Subtree]`), used to pull every descendant taxon of a
    # node - confirmed real usage in rentrez, taxize, and phylotaR. Datasets'
    # --children flag does the same in one call instead of walking the
    # taxonomy tree by hand via repeated elink.
    tags = extract_field_tags(req.term or "")
    subtree = tags.get("subtree")
    taxon = req.ids or subtree or (req.term.strip() if req.term else None)
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
    reason = "Taxonomy lookup by ID or name."
    if subtree:
        cli += " --children"
        rest += "?children=true"
        reason = (
            "Taxonomy lookup including every descendant taxon - Datasets' "
            "--children flag replaces walking the Entrez taxonomy tree by "
            "hand via repeated elink."
        )
    return TranslationResult(True, reason, cli, rest)


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
    protein accession directly to its gene record.

    WP_ protein accessions are a special case, verified live against both
    the CLI and REST: `datasets summary gene accession WP_...` and the REST
    /gene/accession/{accession} path both return zero results for a real
    WP_ accession (WP_ accessions are non-redundant proteins shared across
    many genomes/strains, so there's no single record for a report to
    summarize). `datasets download gene accession WP_...` DOES work -
    confirmed by actually running it and inspecting the downloaded package.
    So the CLI form below switches to `download` for WP_ accessions, and
    the REST field is left unset since no REST path resolves them.

    For WP_ accessions specifically, Datasets can also include flanking
    genomic sequence directly in that download (--include-flanks-bp) -
    confirmed real flag, "WP accessions only" per the Galaxy IUC toolshed
    wrapper (galaxyproject/tools-iuc datasets_gene.xml), and confirmed live
    by actually downloading and inspecting a real flanking-sequence FASTA
    for BPRC-Bioinfo/LRS-Assembler and VDJ-Insights's real-world use case
    (bounding regions of interest during assembly annotation). This tool
    only recognizes a flank request via the --ask plain-language path
    (nl.py sets req.extra['flank_bp']) since there's no real EUtils/EDirect
    flag for it to parse from - EDirect has no flanking-sequence concept."""
    accession = req.ids
    if not accession:
        return TranslationResult(
            False,
            "Need a specific RefSeq nucleotide/protein accession as -id to "
            "resolve to a gene record.",
            eutils_reference=rebuild_eutils_url(req),
        )

    is_wp = accession.upper().startswith("WP_")
    flank_bp = req.extra.get("flank_bp")

    if flank_bp:
        if not is_wp:
            return TranslationResult(
                False,
                "Flanking-sequence download (--include-flanks-bp) is only "
                f"available for WP_ protein accessions, not '{accession}'.",
                eutils_reference=rebuild_eutils_url(req),
            )
        return TranslationResult(
            True,
            "Datasets can include flanking genomic sequence directly in the "
            "gene download for a WP_ protein accession - no need to "
            "separately compute coordinates and run a second nuccore fetch.",
            datasets_cli=f"datasets download gene accession {accession} "
                         f"--include-flanks-bp {flank_bp}",
            datasets_rest=None,
            field_hint="No working REST path resolves WP_ accessions "
                        "(verified live) - use the CLI form shown.",
        )

    if is_wp:
        return TranslationResult(
            True,
            "WP_ protein accessions are shared across many genomes/strains, "
            "so Datasets' gene summary can't resolve a single record for "
            "one (verified live: returns zero results) - download works "
            "because it resolves one exemplar occurrence instead.",
            datasets_cli=f"datasets download gene accession {accession}",
            datasets_rest=None,
            field_hint="No working REST path resolves WP_ accessions "
                        "(verified live) - use the CLI form shown.",
        )

    return TranslationResult(
        True,
        "Datasets resolves a RefSeq nucleotide/protein accession straight to "
        "its gene record - no separate link step needed.",
        datasets_cli=f"datasets summary gene accession {accession}",
        datasets_rest=f"{DATASETS_REST_BASE}/gene/accession/{quote(accession)}",
    )


def _link_gene_to_seq(req: ParsedRequest) -> TranslationResult:
    """gene -> nuccore/protein: the gene *product report*'s transcripts
    array lists every linked accession.

    A prior version of this handler used a jq filter confirmed against a
    Biostars answer (biostars.org/p/478064) - but that filter assumed a
    `.genes[].gene.transcripts[]` wrapper and no `--report product` flag.
    Running it live against the real API failed ("Cannot iterate over
    null"): with plain `datasets summary gene ... --as-json-lines`, each
    line IS the gene object directly (no `.genes[]`/`.gene` wrapper), and
    it has no `transcripts` field at all without `--report product`. The
    filter below was corrected by actually inspecting the real JSON output
    of `datasets summary gene gene-id 672 --report product --as-json-lines`
    and re-running the corrected jq filter successfully against it. There's
    no top-level `proteins[]` fallback for genes with no transcript record
    either (unlike the prior version's unverified claim) - only
    `transcripts[].protein.accession_version` was actually observed."""
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
    jq_filter = (
        r"[.gene_id, .symbol, "
        r"(try .transcripts[].accession_version), "
        r"(try .transcripts[].protein.accession_version)] | @tsv"
    )
    cli = (f"datasets summary gene {locator} --report product --as-json-lines "
           f"| jq -r '{jq_filter}'")
    field_hint = ("transcripts[].accession_version (nucleotide) and "
                  "transcripts[].protein.accession_version (protein).")
    if gene_id:
        rest = f"{DATASETS_REST_BASE}/gene/id/{quote(str(gene_id))}/product_report"
    else:
        # No bare /gene/symbol/{symbol} REST path exists without a taxon -
        # verified against datasets.openapi.yaml and live (404). This elink
        # context has no organism to supply one, so leave REST unset.
        rest = None
        field_hint += (" REST also needs a taxon for symbol lookups "
                        "(/gene/symbol/{symbol}/taxon/{taxon}/product_report) - "
                        "use the CLI form shown, or add a taxon to get a REST URL.")
    return TranslationResult(
        True,
        "The gene product report's transcripts array lists every linked "
        "nucleotide/protein accession - pull them out with jq instead of "
        "elink+efetch.",
        datasets_cli=cli,
        datasets_rest=rest,
        field_hint=field_hint,
    )


def _link_assembly_to_field(cli_field: str, rest_note: str):
    """Factory for assembly-> {bioproject, biosample, taxonomy} links: all
    three live as fields inside the standard genome assembly report."""
    def handler(req: ParsedRequest) -> TranslationResult:
        accession = req.ids
        tags = extract_field_tags(req.term or "")
        organism = tags.get("orgn")
        if accession:
            locator = f"accession {accession}"
            rest = f"{DATASETS_REST_BASE}/genome/accession/{quote(accession)}{GENOME_REPORT_SUFFIX}"
        elif organism:
            locator = f'taxon "{organism}"'
            rest = f"{DATASETS_REST_BASE}/genome/taxon/{quote(organism)}{GENOME_REPORT_SUFFIX}"
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
    """assembly -> nuccore. Two real intents show up in practice
    (biostars.org/p/9544394): wanting just the component accessions (use
    the sequence report), or wanting the actual sequence data (just
    download the genome - the sequence report alone doesn't include FASTA)."""
    accession = req.ids
    if not accession:
        return TranslationResult(
            False,
            "Need an assembly accession to look up its component sequences.",
            eutils_reference=rebuild_eutils_url(req),
        )
    if _wants_download(req):
        return TranslationResult(
            True,
            "You want actual sequence data, not just accessions - download "
            "the genome directly rather than looking up nuccore records one "
            "by one.",
            datasets_cli=f"datasets download genome accession {accession}",
            datasets_rest=f"{DATASETS_REST_BASE}/genome/accession/{quote(accession)}/download",
        )
    cli = (f"datasets summary genome accession {accession} --report sequence "
           f"--as-json-lines | dataformat tsv genome-seq --fields accession,refseq-seq-acc")
    return TranslationResult(
        True,
        "The genome sequence report enumerates every nucleotide accession in "
        "the assembly - this is the assembly->nuccore link, structurally.",
        datasets_cli=cli,
        datasets_rest=f"{DATASETS_REST_BASE}/genome/accession/{quote(accession)}/sequence_reports",
        field_hint="Each entry is one chromosome/scaffold/contig accession. "
                    "If you actually want the FASTA data, not just IDs, use "
                    "'datasets download genome accession' instead.",
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
        datasets_rest=f"{DATASETS_REST_BASE}/genome/taxon/{quote(str(taxon))}{GENOME_REPORT_SUFFIX}",
    )


# The legacy elink for gene orthologs (dbfrom=gene&db=gene&linkname=
# gene_gene_homolog) was retired along with HomoloGene in 2019 and now
# returns empty results - it isn't just "less convenient" than Datasets,
# it doesn't work anymore. Confirmed by multiple independent sources citing
# this exact retirement (e.g. github.com/jaechang-hits/SciAgent-Skills).
# gene_gene_neighbors and other gene->gene linknames are a different,
# unrelated relationship (computed similarity, not orthology) and aren't
# mapped here.
ORTHOLOG_LINKNAMES = {"gene_gene_homolog", "gene_gene_homologs"}


def _link_gene_ortholog(req: ParsedRequest) -> TranslationResult:
    """gene -> gene (self-link): the only real use of this pair in EUtils
    is the now-dead gene_gene_homolog ortholog link. Datasets' --ortholog
    flag (CLI v14+) is the direct, working replacement - not just a nicer
    alternative, the only one that still returns results."""
    linkname = (req.extra.get("name") or req.extra.get("linkname") or "").lower()
    if linkname and linkname not in ORTHOLOG_LINKNAMES:
        return TranslationResult(
            False,
            f"elink gene->gene with linkname={linkname} isn't the ortholog "
            "relationship - no Datasets equivalent is mapped for this link type.",
            eutils_reference=rebuild_eutils_url(req),
        )

    tags = extract_field_tags(req.term or "")
    gene_id = req.ids or tags.get("uid")
    symbol = tags.get("gene") or tags.get("sym")
    if not (gene_id or symbol):
        return TranslationResult(
            False,
            "Need a Gene ID or symbol to look up orthologs.",
            eutils_reference=rebuild_eutils_url(req),
        )

    taxa = req.extra.get("ortholog_taxa") or "all"
    reason = (
        "elink's gene->gene 'homolog' link (linkname=gene_gene_homolog) was "
        "retired along with HomoloGene in 2019 and returns empty results - "
        "Datasets' --ortholog is the only working equivalent now, not just "
        "a nicer one."
    )
    if gene_id:
        rest = f"{DATASETS_REST_BASE}/gene/id/{quote(str(gene_id))}/orthologs"
        if taxa != "all":
            # taxon_filter is a real query param on this endpoint - verified
            # against datasets.openapi.yaml and live.
            rest += f"?{urlencode({'taxon_filter': taxa})}"
        return TranslationResult(
            True, reason,
            datasets_cli=f"datasets summary gene gene-id {gene_id} --ortholog {taxa}",
            datasets_rest=rest,
        )
    # The REST API's /orthologs endpoint only exists in a by-gene-id form
    # (confirmed against ncbi/datasets' datasets.openapi.yaml - no
    # /gene/symbol/.../orthologs path exists), but the CLI resolves a
    # symbol to its gene ID internally before requesting orthologs, so the
    # CLI form still works with just a symbol.
    return TranslationResult(
        True, reason,
        datasets_cli=f"datasets summary gene symbol {symbol} --ortholog {taxa}",
        datasets_rest=None,
        field_hint="The REST /orthologs endpoint needs a numeric gene ID, not a "
                    "symbol - resolve via /gene/symbol/{symbol} first, or use the "
                    "CLI form shown, which resolves the symbol internally.",
    )


ELINK_MAP = {
    ("nuccore", "gene"): _link_seq_to_gene,
    ("protein", "gene"): _link_seq_to_gene,
    ("gene", "nuccore"): _link_gene_to_seq,
    ("gene", "protein"): _link_gene_to_seq,
    ("gene", "gene"): _link_gene_ortholog,
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
