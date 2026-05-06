# GDP Macroeconomic Research Agent

A [LangChain Deep Agents](https://docs.langchain.com/oss/python/deepagents/overview) project that performs GDP and macroeconomic analysis using [You.com's Finance Research API](https://you.com/docs/research/overview) via MCP.

## How It Works

The agent decomposes broad macroeconomic questions into precise queries, sends them to You.com's Finance Research API through the `you-finance` MCP tool, and synthesizes the cited results into a structured report. The Finance Research API handles the heavy lifting internally — multi-step research, source verification against World Bank/IMF/Eurostat/OECD, and citation generation — so the agent focuses on query planning and report assembly.

## Project Structure

```
├── .mcp.json                    # You.com MCP server config (filtered to you-finance only)
├── skills/
│   └── you-finance/
│       └── SKILL.md             # Finance Research API orchestration skill
├── src/
│   └── gdp_research/
│       ├── agent.py             # Deep Agent setup with MCP tools
│       ├── prompts.py           # System prompts and workflow
│       └── output.py            # Markdown/JSON report formatters
└── examples/
    └── eu_gdp_analysis.py       # EU GDP analysis example
```

## Setup

### Prerequisites

- Python 3.14+
- [uv](https://docs.astral.sh/uv/)

### Install

```bash
uv sync
```

### Environment Variables

Copy `.env.example` to `.env` and fill in your keys:

```
ANTHROPIC_API_KEY=your_anthropic_api_key
YDC_API_KEY=your_you_com_api_key
LANGSMITH_API_KEY=your_langsmith_api_key  # Optional
```

## Usage

### Run the example

```bash
# Markdown report (default)
uv run python examples/eu_gdp_analysis.py

# JSON output
uv run python examples/eu_gdp_analysis.py --format json
```

### Use programmatically

```python
import asyncio
from gdp_research.agent import run_gdp_research

report = asyncio.run(run_gdp_research(
    query="What was the GDP in 2022 for each EU country? Highlight anomalies and break down contributing industries.",
    output_format="markdown",
))
```

## Architecture

The agent uses a thin orchestration layer on top of the Finance Research API:

1. **Decompose** — Break the user's question into scoped `you-finance` queries with the right effort level (`standard`, `deep`, or `exhaustive`) and source control.
2. **Query** — Call `you-finance` via MCP. The API internally runs parallel research branches, consults structured public data, and returns cited answers with `[[n]]` source tags.
3. **Synthesize** — Merge results from multiple tool calls into a unified report with re-numbered citations.

The agent does **not** duplicate work the Finance Research API already handles (source verification, cross-referencing, multi-step evidence gathering).