"""EU GDP Analysis Example

Runs the GDP research agent with the target query:
Analyze GDP for EU economic zone countries in 2022, identify anomalies,
break down industries, and investigate macroeconomic trends.

Usage:
    uv run python examples/eu_gdp_analysis.py
    uv run python examples/eu_gdp_analysis.py --format json
"""

import argparse
import asyncio
import os
import sys

from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from gdp_research.agent import run_gdp_research

QUERY = (
    "What was the GDP in 2022 for each country within the EU economic zone. "
    "Highlight those that are increasing or decreasing at an anomalous rate. "
    "Specify and break down which industries are causing these shifts and "
    "investigate macroeconomic trends within each country that are contributing."
)


async def main():
    load_dotenv()

    parser = argparse.ArgumentParser(description="EU GDP Research Agent")
    parser.add_argument(
        "--format",
        choices=["markdown", "json"],
        default="markdown",
        help="Output format (default: markdown)",
    )
    args = parser.parse_args()

    report = await run_gdp_research(
        query=QUERY,
        output_format=args.format,
        thread_id="eu-gdp-2022",
    )

    output_file = f"eu_gdp_report.{'json' if args.format == 'json' else 'md'}"
    with open(output_file, "w") as f:
        if args.format == "json":
            f.write(report.to_json_string())
        else:
            f.write(report.to_markdown())

    print(f"\nReport saved to {output_file}")


if __name__ == "__main__":
    asyncio.run(main())
