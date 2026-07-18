"""Command-line entry point.

This tool only explains equivalences between EUtils/EDirect and NCBI
Datasets API v2 - it never calls, forwards, or executes any request.

Usage:
    # Translate an EUtils/EDirect call
    python -m eutils2datasets.cli 'esearch -db gene -query "BRCA1[gene] AND human[orgn]"'
    python -m eutils2datasets.cli --format rest 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=assembly&id=GCF_000001405.40'

    # Ask in plain language instead
    python -m eutils2datasets.cli --ask "find the BRCA1 gene in human"
    python -m eutils2datasets.cli --ask "what bioproject is GCF_000001405.40 from?"
"""
import argparse
import sys

from .parser import parse
from .translator import translate
from .nl import interpret


def _format_result(result, fmt: str) -> str:
    lines = []
    if result.supported:
        lines.append(f"Datasets equivalent found: {result.reason}")
        if fmt in ("cli", "both") and result.datasets_cli:
            lines.append(f"  CLI : {result.datasets_cli}")
        if fmt in ("rest", "both") and result.datasets_rest:
            lines.append(f"  REST: {result.datasets_rest}")
        if result.field_hint:
            lines.append(f"  note: {result.field_hint}")
    else:
        lines.append(f"No Datasets equivalent: {result.reason}")
        if result.eutils_reference:
            lines.append(f"  Continue using EUtils/EDirect for this: {result.eutils_reference}")
    return "\n".join(lines)


def run_call(input_text: str, fmt: str) -> str:
    req = parse(input_text)
    return _format_result(translate(req), fmt)


def run_ask(question: str, fmt: str) -> str:
    return _format_result(interpret(question), fmt)


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Explain the NCBI Datasets API v2 equivalent of an "
                     "EUtils/EDirect request, where one exists. This tool "
                     "only explains - it doesn't call or forward anything."
    )
    group = ap.add_mutually_exclusive_group()
    group.add_argument("input", nargs="?", help="EUtils URL or EDirect command string")
    group.add_argument("--ask", metavar="QUESTION",
                        help="Ask in plain language instead of writing an EUtils/EDirect call")
    ap.add_argument("--file", help="File with one EUtils/EDirect request per line")
    ap.add_argument(
        "--format", choices=["cli", "rest", "both"], default="both",
        help="Output form for Datasets equivalents (default: both)"
    )
    args = ap.parse_args(argv)

    if args.ask:
        print(run_ask(args.ask, args.format))
        return 0

    requests = []
    if args.file:
        with open(args.file) as fh:
            requests = [line.strip() for line in fh if line.strip()]
    elif args.input:
        requests = [args.input]
    else:
        ap.print_help()
        return 1

    for i, text in enumerate(requests):
        if len(requests) > 1:
            print(f"--- request {i + 1} ---")
        print(run_call(text, args.format))
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
