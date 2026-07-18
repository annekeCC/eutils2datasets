# eutils2datasets

Explains the [NCBI Datasets API v2](https://www.ncbi.nlm.nih.gov/datasets/docs/v2/) equivalent of an EUtils/EDirect request, or of a plain-language question about NCBI data — where an equivalent exists. **This is a translation/explanation tool only: it never calls, forwards, or executes any request.** Its output is something you copy and run yourself.

## Why this can't be a full translator

[EUtils](https://www.ncbi.nlm.nih.gov/books/NBK25501/) / [EDirect](https://www.ncbi.nlm.nih.gov/books/NBK179288/) cover the entire Entrez ecosystem: PubMed, Nucleotide, Protein, SRA, BioProject, arbitrary free-text boolean search, cross-database linking (`elink`), and more. **NCBI Datasets API v2 is much narrower** — it's built around structured lookups for **genes, genome assemblies, and taxonomy** (plus virus data, not yet handled here), returning JSON reports or downloadable zip packages, not general Entrez search results.

So translation only covers the slice of EUtils/EDirect that maps onto those three Datasets categories:

| Condition | Datasets mapping |
|---|---|
| `db=gene` + Gene ID (`-id` or `[uid]`) | `gene/id/{id}` |
| `db=gene` + symbol (`[gene]`/`[sym]`), optional `[orgn]` | `gene/symbol/{symbol}[/taxon/{taxon}]` |
| `db=assembly` + accession (`GCF_`/`GCA_`) | `genome/accession/{accession}` |
| `db=assembly` + `[orgn]` | `genome/taxon/{taxon}` |
| `db=taxonomy` + ID or name | `taxonomy/taxon/{id_or_name}` |

Everything else — PubMed searches, arbitrary Nucleotide/Protein fetches, `einfo`, `epost`, free-text boolean queries with OR/NOT/grouping, and most `elink` traversals — has **no translation**. The result explains why, and shows the equivalent EUtils/EDirect call for reference so you know what you're still working with — it's information, not something the tool runs for you.

`efetch`/EDirect `-format`/`rettype` values that imply an actual sequence download (`fasta`, `gb`, `gff3`, etc.) map to `datasets download ...` instead of `datasets summary ...`.

## elink: cross-database links that are actually report fields

A lot of `elink` traffic isn't really graph traversal — it's asking for a value that's already embedded in a Datasets metadata report.

| elink (source → target) | Datasets equivalent |
|---|---|
| `nuccore`/`protein` → `gene` | `datasets summary gene accession {accession}` — resolves a RefSeq nucleotide/protein accession straight to its gene record |
| `gene` → `nuccore`/`protein` | the gene report's `transcripts`/`proteins` arrays list every linked accession — pulled out with `jq` |
| `assembly` → `bioproject` | `assminfo-bioproject-accession` field in the standard genome report |
| `assembly` → `biosample` | `assminfo-biosample-accession` field in the standard genome report |
| `assembly` → `taxonomy` | `tax-id` field in the standard genome report |
| `assembly` → `nuccore` | genome **sequence report** enumerates every chromosome/scaffold/contig accession — or, if you want actual sequence data rather than just the accession list, `datasets download genome accession` directly |
| `taxonomy` → `assembly` | `datasets summary genome taxon {taxon}` — not a field extraction, but the direct structural equivalent (every assembly for a taxon in one call) |

Everything else (`elink` into/out of PubMed, SRA, BioSample-as-source, etc.) has no translation, since Datasets has no representation of that relationship at all.

**Note on field names:** most `elink` translations pipe output through `dataformat` using its documented `--fields` mnemonics (e.g. `tax-id`, `assminfo-accession`) rather than raw JSON paths, because the raw JSON schema has drifted across Datasets API versions (nesting and casing both change) — `dataformat` mnemonics are the stable, documented interface. Run `dataformat tsv <report> --help` to confirm an exact name if a pipeline depends on it. The `gene`→`nuccore`/`protein` link is the one exception: it uses a real, confirmed JSON path via `jq` (see below) rather than a `dataformat` mnemonic.

## Verified against real usage

A few of the mappings above have been checked against real Q&A threads (not just NCBI's own docs), which caught one hedge that needed fixing and confirmed two important boundaries:

- **Fixed:** the gene→nuccore/protein link previously used a guessed `dataformat` mnemonic. A real answer from an NCBI Datasets team member ([biostars.org/p/478064](https://www.biostars.org/p/478064/)) shows the actual JSON path — `transcripts[].accession_version`, `transcripts[].protein.accession_version`, and `proteins[].accession_version` for gene records with no transcript (e.g. some mitochondrial genes) — now used directly via `jq` instead.
- **Confirmed:** `assembly→nuccore` splits into two real intents ([biostars.org/p/9544394](https://www.biostars.org/p/9544394/)) — wanting just the component accessions (sequence report) vs. wanting the actual sequence data, where `datasets download genome accession` is simpler than looking up each nuccore record. This tool distinguishes them by download-intent rettype, same as elsewhere.
- **Confirmed as a real boundary, not a gap in this tool:** `nuccore→assembly` (going from a sequence accession to its assembly) has no Datasets equivalent — real users still resolve it via `elink -target assembly` ([biostars.org/p/491310](https://www.biostars.org/p/491310/)). Similarly, not every `db=assembly` accession is actually in Datasets' scope — suppressed/historical assemblies may still need EDirect + FTP paths ([biostars.org/p/9497749](https://www.biostars.org/p/9497749/)). This tool can't detect that at translation time (it would need a live API call, not just static mapping), so treat a "translated" assembly result as what *should* work, not a guarantee for every accession.

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
  REST: https://api.ncbi.nlm.nih.gov/datasets/v2/genome/accession/GCF_000001405.40
```

### Ask in plain language instead

```bash
$ python3 -m eutils2datasets.cli --ask "what bioproject is GCF_000001405.40 from?"
Datasets equivalent found: The linked BioProject accession is already a field in the standard genome report.
  CLI : datasets summary genome accession GCF_000001405.40 --as-json-lines | dataformat tsv genome --fields assminfo-accession,assminfo-bioproject-accession
  REST: https://api.ncbi.nlm.nih.gov/datasets/v2/genome/accession/GCF_000001405.40
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
- Virus-specific Datasets endpoints aren't mapped yet — viral genome requests via `db=nuccore`/`assembly` currently have no translation.
- EDirect pipelines are parsed for their net effect (db/query/id/format), not simulated stage-by-stage — fine for translation purposes, since only the endpoint being targeted matters, not intermediate `xtract` shaping.
- `elink` coverage is limited to the (source, target) pairs in `ELINK_MAP` in `translator.py`.
- `--ask` is heuristic pattern matching, not true language understanding — unusual phrasing, multiple entities in one question, or intents outside `nl.py`'s pattern lists will get an honest "couldn't tell" rather than a guess.
- elink translations point to a *report* call, not a call that returns only the linked IDs — the REST response includes the full report, and `field_hint` / the `dataformat --fields`/`jq` filter in the CLI form point at which part of it is the actual link.

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
- [`tests/test_translate.py`](tests/test_translate.py) — example cases (call translation + plain-language), including cases sourced from real Biostars threads
- [`examples.ipynb`](examples.ipynb) — the same examples, interactively
