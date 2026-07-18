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
