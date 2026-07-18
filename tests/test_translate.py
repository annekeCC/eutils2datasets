import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from eutils2datasets import parse, translate, interpret

CALL_CASES = [
    # --- should translate ---
    'esearch -db gene -query "BRCA1[gene] AND human[orgn]"',
    'efetch -db assembly -id GCF_000001405.40 -format docsum',
    'esearch -db taxonomy -query "Mus musculus"',
    'efetch -db gene -id 672',
    "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=gene&term=BRCA1[gene]+AND+human[orgn]",
    'esearch -db assembly -query "Homo sapiens[orgn] AND latest[filter]"',
    'efetch -db assembly -id GCF_000001405.40 -format fasta',

    # --- should have no Datasets equivalent ---
    'esearch -db pubmed -query "CRISPR AND cancer"',
    'efetch -db nuccore -id NM_007294 -format fasta',
    'esearch -db gene -query "(BRCA1[gene] OR BRCA2[gene]) AND human[orgn]"',
    'elink -db gene -target pubmed -id 672',
    'einfo -db gene',

    # --- elink cases that DO have a Datasets equivalent ---
    'elink -db nuccore -target gene -id NM_007294',
    'elink -db protein -target gene -id NP_000483.3',
    'elink -db gene -target nuccore -id 672',
    'elink -db assembly -target bioproject -id GCF_000001405.40',
    'elink -db assembly -target biosample -id GCF_000001405.40',
    'elink -db assembly -target nuccore -id GCF_000001405.40',
    'elink -db assembly -target taxonomy -id GCF_000001405.40',
    'elink -db taxonomy -target assembly -id 9606',
    "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/elink.fcgi?dbfrom=protein&db=gene&id=NP_000483.3",
    'elink -db pubmed -target nuccore -id 12345678',

    # --- from real Biostars threads (see README "Verified against real usage") ---
    'elink -db protein -target gene -id NP_001001127.1',           # biostars.org/p/478064
    'esearch -db gene -query "TP53[gene] AND human[orgn]"',         # biostars.org/p/9543878
    'elink -db assembly -target nuccore -id GCF_001310775.1 -format fasta',  # biostars.org/p/9544394 (download intent)
    'elink -db assembly -target nuccore -id GCF_001310775.1',       # same pair, accession-list intent
    'elink -db nuccore -target assembly -id NC_000913',             # biostars.org/p/491310 - NO Datasets equivalent

    # --- ortholog sets: legacy elink is dead (retired w/ HomoloGene, 2019) ---
    'elink -db gene -target gene -id 672 -name gene_gene_homolog',
    'elink -db gene -target gene -id 672 -name gene_gene_neighbors',  # wrong linkname, not orthology -> unsupported
    'elink -db gene -target gene -id 672',  # no linkname given -> still resolvable

    # --- bulk/filtered assembly search at taxon scale (comparative genomics) ---
    'esearch -db assembly -query "Escherichia coli[orgn] AND \\"complete genome\\"[Assembly Level]"',
    'esearch -db assembly -query "bacteria[orgn] AND \\"reference genome\\"[RefSeq Category]"',
    'esearch -db assembly -query "archaea[orgn] AND srcdb_refseq[PROP]"',
    'esearch -db assembly -query "Vibrio[orgn] AND type_material[Filter]"',
    'esearch -db assembly -query "Escherichia coli[orgn] AND \\"complete genome\\"[Assembly Level] AND srcdb_refseq[PROP]"',

    # --- taxonomy subtree traversal ---
    'esearch -db taxonomy -query "9606[Subtree]"',
    'esearch -db taxonomy -query "\\"Escherichia\\"[Subtree]"',
]

ASK_CASES = [
    "find the BRCA1 gene in human",
    "what gene is NM_007294 from?",
    "genome assembly for GCF_000001405.40",
    "genome for human",
    "taxonomy id for mouse",
    "what bioproject is GCF_000001405.40 from?",
    "what biosample is this assembly GCF_000001405.40 from?",
    "what chromosomes make up the assembly GCF_000001405.40?",
    "what species is GCF_000001405.40?",
    "what assemblies are available for this species tax id 9606?",
    "find me some papers about CRISPR",  # should fail to map (no db keyword match)
    "hello",  # should fail entirely
    "orthologs of BRCA1 in mammals",
    "ortholog set for TP53 across primates",
    "orthologs of nonexistentgenexyz",  # no symbol found via stoplist edge case -> should still find a symbol, but no taxa
    "100 bp flanking sequence for WP_003249567.1",
    "flanking sequence for WP_003249567.1",  # no bp given -> should fail cleanly
]

print("=" * 20, "CALL TRANSLATION", "=" * 20)
for case in CALL_CASES:
    req = parse(case)
    result = translate(req)
    tag = "TRANSLATED" if result.supported else "NO EQUIVALENT"
    print(f"[{tag}] {case}")
    print(f"    reason: {result.reason}")
    if result.supported:
        print(f"    cli : {result.datasets_cli}")
        print(f"    rest: {result.datasets_rest}")
        if result.field_hint:
            print(f"    hint: {result.field_hint}")
    else:
        print(f"    eutils reference: {result.eutils_reference}")
    print()

print("=" * 20, "PLAIN-LANGUAGE ASK", "=" * 20)
for case in ASK_CASES:
    result = interpret(case)
    tag = "TRANSLATED" if result.supported else "NO EQUIVALENT / UNCLEAR"
    print(f"[{tag}] {case}")
    print(f"    reason: {result.reason}")
    if result.supported:
        print(f"    cli : {result.datasets_cli}")
        print(f"    rest: {result.datasets_rest}")
        if result.field_hint:
            print(f"    hint: {result.field_hint}")
    print()

print("=" * 20, "ASSERTIONS (new use cases)", "=" * 20)


def check(label, actual, expected):
    status = "PASS" if actual == expected else "FAIL"
    print(f"[{status}] {label}")
    if status == "FAIL":
        print(f"    expected: {expected!r}")
        print(f"    actual  : {actual!r}")
    assert actual == expected, f"{label}: expected {expected!r}, got {actual!r}"


# Ortholog: legacy elink is dead - Datasets --ortholog is the only working path.
r = translate(parse('elink -db gene -target gene -id 672 -name gene_gene_homolog'))
check("ortholog by gene-id: supported", r.supported, True)
check("ortholog by gene-id: cli", r.datasets_cli, "datasets summary gene gene-id 672 --ortholog all")
check("ortholog by gene-id: rest", r.datasets_rest, "https://api.ncbi.nlm.nih.gov/datasets/v2/gene/id/672/orthologs")

r = translate(parse('elink -db gene -target gene -id 672 -name gene_gene_neighbors'))
check("wrong gene->gene linkname: unsupported", r.supported, False)

r = interpret("orthologs of BRCA1 in mammals")
check("ortholog via --ask: cli", r.datasets_cli, "datasets summary gene symbol BRCA1 --ortholog mammals")
check("ortholog via --ask: rest is None (no symbol-based REST path)", r.datasets_rest, None)

# Bulk assembly filters: one call, not an esearch+esummary loop.
r = translate(parse(
    'esearch -db assembly -query '
    '"Escherichia coli[orgn] AND \\"complete genome\\"[Assembly Level] AND srcdb_refseq[PROP]"'
))
check(
    "bulk assembly filters: cli",
    r.datasets_cli,
    'datasets summary genome taxon "Escherichia coli" --assembly-level complete --assembly-source refseq',
)

# Taxonomy subtree.
r = translate(parse('esearch -db taxonomy -query "9606[Subtree]"'))
check("taxonomy subtree: cli", r.datasets_cli, 'datasets summary taxonomy taxon "9606" --children')

# Flanking sequence: WP_ accessions only.
r = interpret("100 bp flanking sequence for WP_003249567.1")
check(
    "flanking sequence via --ask: cli",
    r.datasets_cli,
    "datasets download gene accession WP_003249567.1 --include-flanks-bp 100",
)

req = parse('elink -db protein -target gene -id NP_000483.3')
req.extra["flank_bp"] = "100"
r = translate(req)
check("flanking sequence rejected for non-WP accession", r.supported, False)

# --- Live-verification fixes (2026-07-18): every REST/CLI pattern below was
# actually executed against the real datasets CLI binary and/or the live
# REST API, not just checked against docs. See README "Verified live
# against the real API" for what each of these actually caught.

# gene->nuccore/protein: corrected jq filter (previous version failed live
# with "Cannot iterate over null" - needed --report product and no
# .genes[].gene wrapper).
r = translate(parse('elink -db gene -target nuccore -id 672'))
check("gene->seq: cli uses --report product", "--report product" in r.datasets_cli, True)
check("gene->seq: cli has no wrong .genes[].gene wrapper", ".genes[]" in r.datasets_cli, False)
check("gene->seq: rest uses product_report", r.datasets_rest,
      "https://api.ncbi.nlm.nih.gov/datasets/v2/gene/id/672/product_report")

# genome REST URLs need /dataset_report - bare /genome/accession/{acc} and
# /genome/taxon/{taxon} both 404 live; verified the suffixed form returns 200.
r = translate(parse('efetch -db assembly -id GCF_000001405.40'))
check("assembly accession: rest has /dataset_report", r.datasets_rest,
      "https://api.ncbi.nlm.nih.gov/datasets/v2/genome/accession/GCF_000001405.40/dataset_report")

# WP_ accessions: `summary gene accession` returns zero results live for a
# real WP_ accession; `download` works. No REST path resolves WP_ at all.
r = translate(parse('elink -db protein -target gene -id WP_003249567.1'))
check("WP_ accession (no flank): uses download not summary", r.datasets_cli,
      "datasets download gene accession WP_003249567.1")
check("WP_ accession (no flank): rest is None (verified live, no path works)", r.datasets_rest, None)

# gene symbol without a taxon: no bare /gene/symbol/{symbol} REST path
# exists (404 live) - taxon is required.
r = translate(parse('esearch -db gene -query "BRCA1[gene]"'))
check("gene symbol, no taxon: rest is None (REST requires a taxon)", r.datasets_rest, None)

# taxonomy subtree REST includes ?children=true (verified live, returns
# populated children[] array).
r = translate(parse('esearch -db taxonomy -query "9606[Subtree]"'))
check("taxonomy subtree: rest includes children=true", r.datasets_rest,
      "https://api.ncbi.nlm.nih.gov/datasets/v2/taxonomy/taxon/9606?children=true")

# bulk assembly filters: REST query param values differ from CLI flag
# values (REST wants complete_genome, CLI wants complete) - verified both
# forms live, together, against a real filtered query.
r = translate(parse(
    'esearch -db assembly -query '
    '"Escherichia coli[orgn] AND \\"complete genome\\"[Assembly Level] AND srcdb_refseq[PROP]"'
))
check(
    "bulk assembly filters: rest",
    r.datasets_rest,
    "https://api.ncbi.nlm.nih.gov/datasets/v2/genome/taxon/Escherichia%20coli/dataset_report"
    "?filters.assembly_level=complete_genome&filters.assembly_source=refseq",
)

print()
print("All assertions passed.")
