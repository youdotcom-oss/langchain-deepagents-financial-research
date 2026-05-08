"""Software Valuations Analysis Example

Runs the finance research agent with the software_valuations preset to analyze
median revenue and EBITDA multiples for public software companies across
Consumer, SaaS, and Enterprise segments over the last five years.

Usage:
    uv run python examples/software_valuations.py
    uv run python examples/software_valuations.py --format json
"""

import argparse
import asyncio
import os
import sys
from datetime import datetime

from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from finance_research.agent import run_finance_research

QUERY = (
    "What is the median revenue and EBITDA multiple for public software companies "
    "over the last five years. Investigate Consumer, SaaS, and Enterprise industry "
    "companies separately. Return required numbers for overall calculations to be "
    "verified and to confirm industry category label."
)


async def main():
    load_dotenv()

    parser = argparse.ArgumentParser(description="Software Valuations Research Agent")
    parser.add_argument(
        "--format",
        choices=["markdown", "json"],
        default="markdown",
        help="Output format (default: markdown)",
    )
    args = parser.parse_args()

    report = await run_finance_research(
        query=QUERY,
        preset="software_valuations",
        output_format=args.format,
        thread_id="software-valuations-5yr",
    )

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    ext = "json" if args.format == "json" else "md"
    output_file = f"software_valuations_report_{ts}.{ext}"
    with open(output_file, "w") as f:
        if args.format == "json":
            f.write(report.to_json_string())
        else:
            f.write(report.to_markdown())

    print(f"\nReport saved to {output_file}")


if __name__ == "__main__":
    asyncio.run(main())
