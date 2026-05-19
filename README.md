# Finance Research Agent

A [LangChain Deep Agents](https://docs.langchain.com/oss/python/deepagents/overview) project that performs financial research using [You.com's Finance Research API](https://you.com/docs/research/overview). Ships with two presets — **GDP macroeconomic analysis** and **software company valuations** — and is designed to make it easy to add more.

## How It Works

The agent decomposes broad financial questions into precise queries, sends them to You.com's Finance Research API through the `you-finance` tool, and synthesizes the cited results into a structured report. The Finance Research API handles the heavy lifting internally — multi-step research, source verification, and citation generation — so the agent focuses on query planning and report assembly.

## Presets

| Preset | Description | Example Query |
|--------|-------------|---------------|
| `gdp` | GDP and macroeconomic analysis across countries/regions | EU GDP by country with anomaly detection |
| `software_valuations` | Public software company valuation multiples | Median EV/Revenue and EV/EBITDA by segment |

Each preset provides a tailored system prompt, query decomposition strategy, and report structure. The underlying tool, skill files, and agent machinery are shared.

## Project Structure

```
├── .mcp.json                    # You.com MCP server config (alternative transport)
├── skills/
│   └── youdotcom-finance-research/
│       ├── SKILL.md             # Finance Research API orchestration skill
│       └── openapi_finance_research.yaml # OpenAPI spec for reference
├── src/
│   └── finance_research/
│       ├── agent.py             # Deep Agent setup with HTTP/MCP tool
│       ├── prompts.py           # Preset system prompts and workflows
│       └── output.py            # Markdown/JSON report formatters
└── examples/
    ├── eu_gdp_analysis.py       # GDP preset example
    └── software_valuations.py   # Software valuations preset example
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

### Run the examples

```bash
# GDP analysis (default preset)
uv run python examples/eu_gdp_analysis.py

# Software valuations analysis
uv run python examples/software_valuations.py

# JSON output
uv run python examples/software_valuations.py --format json
```

### Use programmatically

```python
import asyncio
from finance_research.agent import run_finance_research

# GDP preset
report = asyncio.run(run_finance_research(
    query="What was the GDP in 2022 for each EU country?",
    preset="gdp",
))

# Software valuations preset
report = asyncio.run(run_finance_research(
    query="Median revenue and EBITDA multiples for public software companies over 5 years",
    preset="software_valuations",
))
```

## Architecture

The agent uses a thin orchestration layer on top of the Finance Research API:

1. **Preset selection** — Choose a research preset (`gdp` or `software_valuations`) that configures the system prompt, query decomposition strategy, and report structure.
2. **Decompose** — Break the user's question into scoped `youdotcom-finance-research` queries with the right effort level (`standard`, `deep`, or `exhaustive`) and source control.
3. **Query** — Call `youdotcom-finance-research` via direct HTTP (or MCP). The API internally runs parallel research branches, consults structured public data, and returns cited answers with `[[n]]` source tags.
4. **Synthesize** — Merge results from multiple tool calls into a unified report with re-numbered citations.

The agent does **not** duplicate work the Finance Research API already handles (source verification, cross-referencing, multi-step evidence gathering).

## Tool Transport

The agent supports two methods for calling the Finance Research API, controlled by `TOOL_TRANSPORT` in `agent.py`:

- **`http`** (default) — Direct HTTP POST via `httpx`. Simpler, no MCP overhead.
- **`mcp`** — Uses the You.com MCP server via `langchain-mcp-adapters`. Useful if you want the standard MCP tool interface.

Both methods are fully implemented; swap by changing a single constant.
