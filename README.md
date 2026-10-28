# eutils2datasets

Explains the [NCBI Datasets API v2](https://www.ncbi.nlm.nih.gov/datasets/docs/v2/) equivalent of an EUtils/EDirect request, or of a plain-language question about NCBI data — where an equivalent exists. **This is a translation/explanation tool only: it never calls, forwards, or executes any request.** Its output is something you copy and run yourself.

This project was developed using Claude Code.

## Why this can't be a full translator

[EUtils](https://www.ncbi.nlm.nih.gov/books/NBK25501/) / [EDirect](https://www.ncbi.nlm.nih.gov/books/NBK179288/) cover the entire Entrez ecosystem: PubMed, Nucleotide, Protein, SRA, BioProject, arbitrary free-text boolean search, cross-database linking (`elink`), and more. **NCBI Datasets API v2 is much narrower** — it's built around structured lookups for **genes, genome assemblies, and taxonomy** (plus virus data, not yet handled here), returning JSON reports or downloadable zip packages, not general Entrez search results.

So translation only covers the slice of EUtils/EDirect that maps onto those three Datasets categories:

| Condition | Datasets mapping |
|---|---|
| `db=gene` + Gene ID (`-id` or `[uid]`) | `gene/id/{id}` |
| `db=gene` + symbol (`[gene]`/`[sym]`), optional `[orgn]` | `gene/symbol/{symbol}[/taxon/{taxon}]` for the CLI - REST always requires the `/taxon/{taxon}` part (verified live), so a symbol with no organism only gets a CLI form, no REST URL |
| `db=assembly` + accession (`GCF_`/`GCA_`) | `genome/accession/{accession}/dataset_report` (REST has no bare form - verified live) |
| `db=assembly` + `[orgn]` | `genome/taxon/{taxon}/dataset_report` (same REST caveat) |
| `db=assembly` + `[orgn]` + `[Assembly Level]`/`[RefSeq Category]`/`srcdb_refseq[PROP]`/`type_material[Filter]` | same `genome/taxon/{taxon}` call, with `--assembly-level`/`--reference`/`--assembly-source refseq`/`--from-type` folded in — see [Complex use cases #2](#2-bulk-filtered-genome-search) |
| `db=taxonomy` + ID or name | `taxonomy/taxon/{id_or_name}` |
| `db=taxonomy` + `[Subtree]` | `taxonomy/taxon/{id_or_name}` + `--children` |

Everything else — PubMed searches, arbitrary Nucleotide/Protein fetches, `einfo`, `epost`, free-text boolean queries with OR/NOT/grouping, and most `elink` traversals — has **no translation**. The result explains why, and shows the equivalent EUtils/EDirect call for reference so you know what you're still working with — it's information, not something the tool runs for you.

`efetch`/EDirect `-format`/`rettype` values that imply an actual sequence download (`fasta`, `gb`, `gff3`, etc.) map to `datasets download ...` instead of `datasets summary ...`.

## elink: cross-database links that are actually report fields

A lot of `elink` traffic isn't really graph traversal — it's asking for a value that's already embedded in a Datasets metadata report.

| elink (source → target) | Datasets equivalent |
|---|---|
| `nuccore`/`protein` → `gene` | `datasets summary gene accession {accession}` — resolves a RefSeq nucleotide/protein accession straight to its gene record. For WP_ accessions specifically, `summary` returns zero results (verified live) — this tool uses `download gene accession {accession}` instead for those |
| `gene` → `nuccore`/`protein` | the gene **product report**'s `transcripts` array lists every linked accession — pulled out with `jq` |
| `assembly` → `bioproject` | `assminfo-bioproject-accession` field in the standard genome report |
| `assembly` → `biosample` | `assminfo-biosample-accession` field in the standard genome report |
| `assembly` → `taxonomy` | `tax-id` field in the standard genome report |
| `assembly` → `nuccore` | genome **sequence report** enumerates every chromosome/scaffold/contig accession — or, if you want actual sequence data rather than just the accession list, `datasets download genome accession` directly |
| `taxonomy` → `assembly` | `datasets summary genome taxon {taxon}` — not a field extraction, but the direct structural equivalent (every assembly for a taxon in one call) |
| `gene` → `gene` (`linkname=gene_gene_homolog`) | `datasets summary gene ... --ortholog {taxa}` — the *only* working path, not just a nicer one; see [Complex use cases #1](#1-ortholog-sets) |

Everything else (`elink` into/out of PubMed, SRA, BioSample-as-source, other `gene`→`gene` linknames like `gene_gene_neighbors`, etc.) has no translation, since Datasets has no representation of that relationship at all.

**Note on field names:** most `elink` translations pipe output through `dataformat` using its documented `--fields` mnemonics (e.g. `tax-id`, `assminfo-accession`) rather than raw JSON paths, because the raw JSON schema has drifted across Datasets API versions (nesting and casing both change) — `dataformat` mnemonics are the stable, documented interface. Run `dataformat tsv <report> --help` to confirm an exact name if a pipeline depends on it. The `gene`→`nuccore`/`protein` link is the one exception: it uses a `jq` filter against the raw JSON instead of a `dataformat` mnemonic, verified by actually running it live against the real API (see "Verified live against the real API" below).

## Verified against real usage

A few of the mappings above have been checked against real Q&A threads (not just NCBI's own docs), which caught hedges that needed fixing and confirmed two important boundaries:

- **Fixed (see below for a further correction):** the gene→nuccore/protein link previously used a guessed `dataformat` mnemonic. A real answer from an NCBI Datasets team member ([biostars.org/p/478064](https://www.biostars.org/p/478064/)) pointed at the right area of the response - `transcripts[]`/`protein` fields - as a fix.
- **Confirmed:** `assembly→nuccore` splits into two real intents ([biostars.org/p/9544394](https://www.biostars.org/p/9544394/)) — wanting just the component accessions (sequence report) vs. wanting the actual sequence data, where `datasets download genome accession` is simpler than looking up each nuccore record. This tool distinguishes them by download-intent rettype, same as elsewhere.
- **Confirmed as a real boundary, not a gap in this tool:** `nuccore→assembly` (going from a sequence accession to its assembly) has no Datasets equivalent — real users still resolve it via `elink -target assembly` ([biostars.org/p/491310](https://www.biostars.org/p/491310/)). Similarly, not every `db=assembly` accession is actually in Datasets' scope — suppressed/historical assemblies may still need EDirect + FTP paths ([biostars.org/p/9497749](https://www.biostars.org/p/9497749/)). This tool can't detect that at translation time (it would need a live API call, not just static mapping), so treat a "translated" assembly result as what *should* work, not a guarantee for every accession.
- **Confirmed the legacy ortholog `elink` is actually dead, not just less convenient:** `dbfrom=gene&db=gene&linkname=gene_gene_homolog` was retired along with HomoloGene in 2019 and returns empty results — confirmed by multiple independent sources (e.g. [jaechang-hits/SciAgent-Skills](https://github.com/jaechang-hits/SciAgent-Skills/blob/main/skills/genomics-bioinformatics/databases/gene-database/SKILL.md)).
- **Confirmed real EDirect field-tag syntax for `db=assembly` filters:** `"complete genome"[Assembly Level]`, `"reference genome"[RefSeq Category]`, and `srcdb_refseq[PROP]` all show up in real scripts (e.g. [brinkmanlab/MicrobeDB](https://github.com/brinkmanlab/MicrobeDB/blob/master/update.sh), [ncbi-cxx-toolkit-public](https://github.com/ncbi/ncbi-cxx-toolkit-public)).
- **Confirmed `[Subtree]` as a real taxonomy field tag:** used across established R bioinformatics packages (`rentrez`, `taxize`, `phylotaR`) as `txid{id}[Subtree]` to pull every descendant taxon.

## Verified live against the real API

Everything above was checked against documentation, source code, and real-world usage - not against NCBI's actual servers. That's a real gap: syntax being documented doesn't guarantee a call succeeds (wrong casing, a missing required parameter, an endpoint that needs a different suffix than its sibling endpoints, a case the docs don't call out). So every CLI command and REST URL this tool can generate was re-checked by actually running it - downloading the real `datasets` binary and executing it, and `curl`ing every REST URL - against the live API. That pass found and fixed four real bugs that static verification alone had missed:

- **The gene→nuccore/protein `jq` filter was wrong and failed live** (`jq: error: Cannot iterate over null`). The Biostars-sourced fix above assumed a `.genes[].gene.transcripts[]` wrapper that doesn't exist in `--as-json-lines` output, and needed `--report product` to get transcript data at all (plain `datasets summary gene ...` has no `transcripts` field). Corrected by inspecting the real JSON output of `datasets summary gene gene-id 672 --report product --as-json-lines` and re-running the fixed filter successfully. The claimed `proteins[]` fallback for transcript-less genes was also unverified and has been dropped - only `transcripts[].protein.accession_version` was actually observed to exist.
- **Every genome REST URL this tool generated was wrong.** There is no bare `/genome/accession/{accession}` or `/genome/taxon/{taxon}` endpoint - confirmed against `ncbi/datasets`' own `datasets.openapi.yaml` and live (the bare URL 404s; the same URL with `/dataset_report` appended returns 200 with real data). This was a **pre-existing bug**, not something introduced by today's new features - it affected the original `_translate_assembly`, `_link_assembly_to_field`, and `_link_taxonomy_to_assembly` handlers too. All now append `/dataset_report`.
- **`datasets summary gene accession {accession}` returns zero results for WP_ protein accessions** (confirmed live: `{"total_count": 0}`), and no REST path resolves them either. WP_ accessions are non-redundant proteins shared across many genomes/strains, so there's no single record for a report to summarize. `datasets download gene accession {accession}` does work (confirmed by actually downloading and inspecting a real package) - it resolves one exemplar occurrence instead. The `nuccore`/`protein`→`gene` elink handler now switches to `download` for WP_ accessions and leaves the REST field unset, rather than emitting a command that silently returns nothing.
- **`/gene/symbol/{symbol}` has no bare REST form** - only `/gene/symbol/{symbol}/taxon/{taxon}` exists (confirmed against the spec and live: 404 without a taxon). The CLI doesn't require a taxon for a symbol lookup; REST does. Handlers that build a symbol-only REST URL now leave it unset with a `field_hint` explaining why, instead of pointing at a URL that 404s.

Also confirmed working live, exactly as documented: the ortholog CLI+REST forms (including `taxon_filter`), the bulk assembly filter CLI+REST forms (including that REST's `filters.assembly_level` enum uses `complete_genome` where the CLI flag uses `complete` - the two are verified separately and don't share a value), the taxonomy `--children`/`?children=true` forms, and the WP_ flanking-sequence download (confirmed by downloading a real package and inspecting the actual flanking FASTA sequence inside it).

## Complex real-world use cases

The sections above cover single-record lookups. Real pipelines (found by searching GitHub, Galaxy's toolshed, and public commit history for actual production usage — not hypothetical examples) lean on Datasets for patterns that are more than a one-line EUtils swap. This tool now covers most of them; the rest are documented here so you know what to expect.

### 1. Ortholog sets

**This isn't "nicer" — the old way is broken.** EUtils' only cross-species ortholog link, `elink -db gene -target gene -name gene_gene_homolog`, was retired with HomoloGene in 2019 and silently returns zero results today. Datasets' `--ortholog` flag (CLI v14+) is the *only* working replacement:

```bash
$ python3 -m eutils2datasets.cli 'elink -db gene -target gene -id 672 -name gene_gene_homolog'
Datasets equivalent found: elink's gene->gene 'homolog' link (linkname=gene_gene_homolog) was retired along with HomoloGene in 2019 and returns empty results - Datasets' --ortholog is the only working equivalent now, not just a nicer one.
  CLI : datasets summary gene gene-id 672 --ortholog all
  REST: https://api.ncbi.nlm.nih.gov/datasets/v2/gene/id/672/orthologs
```

Also reachable via `--ask`, e.g. `"orthologs of BRCA1 in mammals"` → `datasets summary gene symbol BRCA1 --ortholog mammals`. There's no real EUtils syntax for a species-filtered ortholog request, so `--ask` is the only path to specifying taxa by name; raw `elink` calls default to `--ortholog all`. A `gene`→`gene` elink with any *other* linkname (e.g. `gene_gene_neighbors`, a different, unrelated relationship) correctly reports no equivalent, rather than guessing.

### 2. Bulk, filtered genome search

**This is the single biggest win, and it really is one call.** Before Datasets, picking "every complete, RefSeq, type-strain genome for this genus" meant an `esearch` against `db=assembly` followed by looping `esummary`/`efetch` over every hit to check each one's assembly level, RefSeq category, and source by hand:

```bash
# the old way: search, then loop and filter client-side
esearch -db assembly -query 'Escherichia coli[orgn]' | \
  esummary | \
  xtract -pattern DocumentSummary -if AssemblyStatus -equals "Complete Genome" \
          -and RefSeq_category -equals "reference genome" \
    -element AssemblyAccession
# ...then still need a separate check for RefSeq-vs-GenBank source and type material
```

Datasets folds every one of those filters into the *same single call* used for a plain organism lookup — no loop, no client-side filtering:

```bash
$ python3 -m eutils2datasets.cli 'esearch -db assembly -query "Escherichia coli[orgn] AND \"complete genome\"[Assembly Level] AND srcdb_refseq[PROP]"'
Datasets equivalent found: Genome lookup by organism/taxon, with every filter folded into one `datasets` call - this replaces what used to be an esearch query followed by a loop of esummary/efetch calls (or manual filtering of the result list) to apply the same criteria.
  CLI : datasets summary genome taxon "Escherichia coli" --assembly-level complete --assembly-source refseq
  REST: https://api.ncbi.nlm.nih.gov/datasets/v2/genome/taxon/Escherichia%20coli/dataset_report?filters.assembly_level=complete_genome&filters.assembly_source=refseq
```

Supported filter tags (all confirmed real EDirect syntax — see "Verified against real usage" above), any combination, ANDed with `[orgn]`:

| EDirect field tag | Datasets flag |
|---|---|
| `"complete genome"[Assembly Level]` (also `chromosome`/`scaffold`/`contig`) | `--assembly-level {level}` |
| `"reference genome"[RefSeq Category]` | `--reference` |
| `srcdb_refseq[PROP]` | `--assembly-source refseq` |
| `type_material[Filter]` | `--from-type` |

This is exactly the pattern real production pipelines use — e.g. [UPHL-BioNGS/Grandeur](https://github.com/UPHL-BioNGS/Grandeur/blob/master/modules/local/datasets_summary/main.nf), a public-health outbreak-surveillance tool, picks reference genomes with `--reference --mag exclude --limit 5` in one call and has **zero** remaining `efetch`/`esearch` calls anywhere in its codebase.

### 3. Dehydrated download + parallel rehydrate

This one is **not a translation of an existing EUtils pattern** — EDirect has nothing structurally similar, so there's no "before" call for this tool to detect and convert. It's worth knowing about anyway because it's how real pipelines fetch genomes at HPC scale (thousands of assemblies, not one):

```bash
datasets download genome taxon 2 --assembly-level complete --dehydrated --filename bacteria.zip
unzip bacteria.zip -d bacteria/
datasets rehydrate --directory bacteria/ --max-workers 10   # 10 matches NCBI's API-key rate limit
```

Step 1 downloads only metadata and a file manifest (fast, small). Step 3 pulls the actual sequence files in parallel afterward — separating "figure out what to download" from "download it" so the second step can be resumed, rate-limited, or run on a different machine (e.g. an HPC compute node) than the first. Used across [nf-core/pathogensurveillance](https://github.com/nf-core/pathogensurveillance), the [Galaxy IUC toolshed's `datasets_genome` tool](https://github.com/galaxyproject/tools-iuc/blob/main/tools/ncbi_datasets/datasets_genome.xml), and [nebiolabs/domainator](https://github.com/nebiolabs/domainator) (which caps `--max-workers` specifically to respect the 10 req/s NCBI API-key limit).

### 4. Taxonomic subtree traversal

`[Subtree]` is real EDirect syntax (`txid9606[Subtree]`) for "this taxon and everything under it" — used in practice to build local reference databases (e.g. every species under a genus, for a Kraken2-style classifier):

```bash
$ python3 -m eutils2datasets.cli 'esearch -db taxonomy -query "9606[Subtree]"'
Datasets equivalent found: Taxonomy lookup including every descendant taxon - Datasets' --children flag replaces walking the Entrez taxonomy tree by hand via repeated elink.
  CLI : datasets summary taxonomy taxon "9606" --children
  REST: https://api.ncbi.nlm.nih.gov/datasets/v2/taxonomy/taxon/9606
```

### 5. Type-strain species identification

Species-identification pipelines using average nucleotide identity (ANI) often need only *type-strain* reference genomes, not every genome for a taxon. This is the same `type_material[Filter]` → `--from-type` mapping from case #2 above, called out separately because it's a distinct real use case (e.g. taxonomic classification pipelines using `--from-type` to build a clean type-strain reference set) rather than a general bulk-download filter.

### 6. Gene flanking-sequence extraction

`--include-flanks-bp` pads a gene download with surrounding genomic sequence — but only works for `WP_` protein accessions (a real, documented CLI constraint, confirmed via the Galaxy IUC toolshed wrapper). There's no EUtils flag for this at all — historically it meant a separate `efetch -db gene` for coordinates, manual arithmetic, then a second `efetch -db nuccore` for the padded region — so this is `--ask`-only:

```bash
$ python3 -m eutils2datasets.cli --ask "100 bp flanking sequence for WP_003249567.1"
Datasets equivalent found: Datasets can include flanking genomic sequence directly in the gene download for a WP_ protein accession - no need to separately compute coordinates and run a second nuccore fetch.
  CLI : datasets download gene accession WP_003249567.1 --include-flanks-bp 100
  note: No working REST path resolves WP_ accessions (verified live) - use the CLI form shown.
```

No REST field is shown here because none actually works for WP_ accessions — see "Verified live against the real API" below. Asking for flanking sequence around a non-`WP_` accession correctly reports unsupported, rather than emitting a flag that would fail.

### 7. A caveat worth flagging, not a confirmed fact

One real, recent (2026) migration commit — [RodrigoOrvate/OASIS](https://github.com/RodrigoOrvate/OASIS/commit/0f69b5b1acb266f6d43dc88635006cc43468ee8b), "replace efetch with Datasets CLI" — cites an "Upcoming NCBI Infrastructure Changes (August 2026)" warning about `efetch` deprecation as its motivation. **This tool could not independently verify a general NCBI-wide `efetch` deprecation** — nothing on NCBI Insights or the E-utilities Bookshelf pages mentions one; the only confirmed 2026 EUtils change found is a narrower `db=pmc` ESearch update landing February 2026. Treat the deprecation claim as one project's own note, not confirmed NCBI policy — but it's a real signal that some maintainers are migrating pre-emptively.

### 8. Out of scope (for now): virus data

[Nextstrain](https://nextstrain.org) — the real-time genomic-epidemiology platform behind outbreak tracking for mpox, RSV, and more — fully replaced its custom NCBI Virus API scripts with `datasets`+`dataformat` in 2023 ([nextstrain/mpox](https://github.com/nextstrain/mpox/commit/82ace30abd07bec140c7e14aee29a46c7bfb28a8), [nextstrain/rsv](https://github.com/nextstrain/rsv/commit/8b11a7a81515a80569d23e717779c1d721264197)). Datasets does cover virus genomes — this tool just doesn't map that db yet (see "Known limitations" below). It's the strongest evidence that Datasets is production-ready for exactly this kind of migration, and the most likely next area to extend.

## Install

No runtime dependencies — everything here is Python standard library.

```bash
git clone <this-repo> eutils2datasets
cd eutils2datasets
pip install -e .          # optional: makes `eutils2datasets` importable from anywhere
python3 -m eutils2datasets.cli --help
```

`pip install -e .` isn't required — running `python3 -m eutils2datasets.cli ...` from the repo root works on its own, since the package directory is right there.

## Usage

### Translate an EUtils URL or EDirect pipeline

```bash
$ python3 -m eutils2datasets.cli 'esearch -db gene -query "BRCA1[gene] AND human[orgn]"'
Datasets equivalent found: Gene lookup by symbol (+ taxon).
  CLI : datasets summary gene symbol BRCA1 --taxon "human"
  REST: https://api.ncbi.nlm.nih.gov/datasets/v2/gene/symbol/BRCA1/taxon/human
```

```bash
$ python3 -m eutils2datasets.cli --format rest \
    'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=assembly&id=GCF_000001405.40'
Datasets equivalent found: Genome lookup by assembly accession.
  REST: https://api.ncbi.nlm.nih.gov/datasets/v2/genome/accession/GCF_000001405.40/dataset_report
```

### Ask in plain language instead

```bash
$ python3 -m eutils2datasets.cli --ask "what bioproject is GCF_000001405.40 from?"
Datasets equivalent found: The linked BioProject accession is already a field in the standard genome report.
  CLI : datasets summary genome accession GCF_000001405.40 --as-json-lines | dataformat tsv genome --fields assminfo-accession,assminfo-bioproject-accession
  REST: https://api.ncbi.nlm.nih.gov/datasets/v2/genome/accession/GCF_000001405.40/dataset_report
  note: Look for the assminfo bioproject accession field in the report.
```

The plain-language mode is a **lightweight heuristic parser, not real NLU** — see "How `--ask` works" below. It reuses the exact same translation logic as the EUtils/EDirect path, so it can't give a different answer than writing out the equivalent call would.

### When there's no equivalent

```bash
$ python3 -m eutils2datasets.cli 'esearch -db pubmed -query "cancer"'
No Datasets equivalent: db=pubmed is outside Datasets API's scope (it covers gene, assembly/genome, and taxonomy only).
  Continue using EUtils/EDirect for this: https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&term=cancer
```

### Batch mode

```bash
python3 -m eutils2datasets.cli --file requests.txt --format cli
```

`requests.txt` should have one EUtils URL or EDirect pipeline per line.

### As a Python library

```python
from eutils2datasets import parse, translate, interpret

# From an EUtils/EDirect call
req = parse('efetch -db gene -id 672 -format docsum')
result = translate(req)
print(result.supported, result.datasets_cli, result.datasets_rest)

# Or from a plain-language question
result = interpret("genome assembly for GCF_000001405.40")
print(result.reason)
```

## How `--ask` works

`interpret()` in `nl.py` looks for a handful of recognizable things in the question — accessions (`GCF_...`, `NM_...`, etc.), gene symbols, taxonomy IDs, organism names — plus phrasing that indicates an elink-style relationship ("bioproject for", "what gene is this", "chromosomes in this assembly", etc.). It builds the same internal request object the EUtils/EDirect path would produce, then runs it through the identical translator. If it can't confidently identify what's being asked for, it says so plainly rather than guessing — see the stoplist and fallback messages in `nl.py` for exactly what's covered.

This intentionally does not use an LLM or any external NLU service — it's a transparent, inspectable set of patterns, so its coverage boundary is exact and documented rather than emergent.

## Notebook

[`examples.ipynb`](examples.ipynb) walks through the examples above interactively, plus a few more edge cases (unsupported boolean queries, elink translations, batch translation of a list of calls, and inspecting the raw `ParsedRequest`/`TranslationResult` dataclasses).

## Known limitations

- Only ANDed, field-tagged terms are parsed (`X[gene] AND Y[orgn]`). Free text, OR/NOT, and parenthetical grouping have no translation, since Datasets' lookups are keyed, not boolean-searchable.
- Virus-specific Datasets endpoints aren't mapped yet — viral genome requests via `db=nuccore`/`assembly` currently have no translation. See [Complex use cases #8](#8-out-of-scope-for-now-virus-data).
- EDirect pipelines are parsed for their net effect (db/query/id/format), not simulated stage-by-stage — fine for translation purposes, since only the endpoint being targeted matters, not intermediate `xtract` shaping.
- `elink` coverage is limited to the (source, target) pairs in `ELINK_MAP` in `translator.py`.
- `--ask` is heuristic pattern matching, not true language understanding — unusual phrasing, multiple entities in one question, or intents outside `nl.py`'s pattern lists will get an honest "couldn't tell" rather than a guess.
- elink translations point to a *report* call, not a call that returns only the linked IDs — the REST response includes the full report, and `field_hint` / the `dataformat --fields`/`jq` filter in the CLI form point at which part of it is the actual link.
- `--ask` doesn't yet parse the bulk assembly filters from case #2 (`--assembly-level`, `--reference`, etc.) out of a plain-language question — those are only reachable via a raw EUtils/EDirect call or URL with the real field tags. Orthologs and flanking sequence, by contrast, are `--ask`-only (see cases #1 and #6), since neither has real EUtils syntax to parse from in the first place.
- `--assembly-level` only recognizes the four level names in `ASSEMBLY_LEVEL_MAP` in `translator.py` (`complete`, `chromosome`, `scaffold`, `contig`); an unrecognized `[Assembly Level]` value is silently dropped rather than passed through, so double-check the CLI output if you use one not in that list.
- Dehydrated download + rehydrate (case #3) isn't translated from anything, since EDirect has no equivalent concept — it's documented, not automated.

## Extending it

- New EUtils db mapping: add a `_translate_<db>` function in `translator.py` and register it in `DB_TRANSLATORS`.
- New elink pair: add a handler function and register it in `ELINK_MAP`.
- New plain-language pattern: add to `LINK_INTENTS` or `DB_INTENTS` in `nl.py`.

`extract_field_tags()` in `parser.py` already handles pulling `[tag]`-style fields out of any EUtils-style query string.

## Project layout

- [`eutils2datasets/model.py`](eutils2datasets/model.py) — `ParsedRequest`/`TranslationResult` dataclasses
- [`eutils2datasets/parser.py`](eutils2datasets/parser.py) — normalizes a raw EUtils URL or EDirect pipeline into a `ParsedRequest`
- [`eutils2datasets/translator.py`](eutils2datasets/translator.py) — maps a `ParsedRequest` to a `TranslationResult` (Datasets CLI/REST, or "not supported")
- [`eutils2datasets/nl.py`](eutils2datasets/nl.py) — lightweight heuristic parser for plain-language questions, reusing the same translator
- [`eutils2datasets/cli.py`](eutils2datasets/cli.py) — command-line entry point (`--ask` for plain language)
- [`tests/test_translate.py`](tests/test_translate.py) — example cases (call translation + plain-language) plus asserted checks for the complex use cases above; cases sourced from real Biostars threads and real EDirect field-tag syntax
- [`examples.ipynb`](examples.ipynb) — the same examples, interactively
