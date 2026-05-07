---
name: you-finance
description: Use this skill when the workflow needs finance-grade research, source-backed numeric answers, or exact public/company/macroeconomic evidence. Invokes the you-finance MCP tool which internally runs multi-step research, consults structured public data (World Bank, IMF, OECD, Eurostat, FRED), verifies sources across parallel branches, and returns cited answers with [[n]] source tags.
allowed-tools: you-finance
---

# Finance Research Agent Orchestration Skill

Use this skill when a broader agentic workflow needs finance-grade research, source-backed numeric answers, or exact public/company/macroeconomic evidence.

## Purpose

The finance research agent is a specialist evidence engine. It is best used as a delegated branch inside a larger workflow when the main agent needs high-confidence finance answers rather than broad conversational search.

It combines several complementary evidence paths:

- You.com deep research for broad discovery and context.
- Structured public-data tools for World Bank, IMF, OECD, and FRED-style macro verification.
- Specialized finance and company-research sources when configured, including company fundamentals, filings, disclosures, market context, and domain-specific knowledge cards.
- Dedicated web search and page fetch for exact filing notes, official reports, benchmark pages, exchange pages, and other page-level evidence.
- A synthesis/citation pass that returns a public response with `[[n]]` source tags.

## When To Use

Use the finance research agent for:

- Public-company filings, annual reports, investor-relations disclosures, earnings metrics, segment tables, contractual obligations, and note-level values.
- Macro questions that need exact country, period, indicator, unit, vintage, or source-family alignment.
- Financial-market and benchmark questions where contract month, instrument, date, field, currency, or unit matters.
- Derived finance calculations where every source input must be retrieved, aligned, and cited before computing.
- Finance answer verification inside a larger agentic plan, especially when another branch produced a plausible but uncited numeric claim.
- Source-constrained finance research, such as limiting evidence to official domains with `source_control.include_domains`.

Prefer the finance research agent over generic web search when the question has any of these properties:

- It asks for a number, ratio, date-specific value, filing value, market value, or official statistic.
- A near miss could be materially wrong, such as adjacent quarter, wrong fiscal year, wrong line item, spot vs futures, stock vs flow, wrong source vintage, wrong unit, or wrong currency.
- The final answer must include citations and be defensible in review.

## When Not To Use

Do not use the finance research agent as the first tool for:

- Non-finance factual questions.
- Lightweight conversational answers that do not require source-backed finance evidence.
- Pure calculation where all inputs are already trusted and available.
- Real-time trading execution, investment advice, or portfolio recommendations.
- Internal endpoint probing. In repo-local orchestration, call the finance service/module directly instead of making HTTP calls to internal endpoints.

## How To Invoke

In an in-process backend workflow, prefer direct service orchestration:

```python
from ydc_services.libs.services.search.schemas.finance_deep_search import (
    FinanceDeepSearchRequest,
)
from ydc_services.services.ai_search.finance_deep_search_service import (
    get_finance_deep_search_service,
)

service = get_finance_deep_search_service()
response = await service.run(
    FinanceDeepSearchRequest(
        input=question,
        research_effort="standard",
        source_control=source_control,
    )
)
```

Use the public API route only when the caller is an external client or a boundary test:

```http
POST /v1/finance/deep_search
```

Request shape:

```json
{
  "input": "What was the latest disclosed value of ...?",
  "research_effort": "standard",
  "source_control": {
    "include_domains": ["sec.gov", "company.com"],
    "freshness": "year",
    "country": "US"
  }
}
```

Response shape:

```json
{
  "output": {
    "content": "The value was $12 million [[1]].",
    "content_type": "text",
    "sources": [
      {
        "url": "https://example.com/source",
        "title": "Source title"
      }
    ]
  }
}
```

The citation contract is strict: final `output.content` should use `[[n]]` tags only. `[[1]]` maps to `output.sources[0]`, `[[2]]` maps to `output.sources[1]`, and so on.

## Orchestration Pattern

For a broader agentic workflow:

1. Classify whether the user question has a finance evidence requirement.
2. Extract the exact checklist: entity, geography, metric, fiscal/calendar period, quarter/month/date, source vintage, unit, scale, currency, stock vs flow, contract month, and output format.
3. Decide the finance research effort:
   - `lite` or `ulow`: quick smoke checks or low-stakes triage.
   - `standard`: default for most finance research.
   - `deep`: difficult filings, conflicting sources, exact macro/statistical values.
   - `exhaustive`: only for high-value tasks where latency/cost are acceptable.
4. Apply `source_control` when the workflow already knows the authoritative domain set.
5. Run the finance research agent as an evidence branch, not as an unbounded conversational agent.
6. Treat the returned answer as a cited research artifact. Preserve its citations when synthesizing with other branches.
7. If multiple branches disagree, prefer the branch with the most direct primary source and exact period/unit alignment.

## Source Control Guidance

Use `include_domains` when the workflow must force official or first-party evidence:

- SEC/company filing questions: `["sec.gov"]` plus the company investor-relations domain if needed.
- US macro/statistics: `["bls.gov", "bea.gov", "fred.stlouisfed.org"]` depending on the metric.
- International macro: official statistical agency, World Bank, IMF, OECD, or central-bank domains.
- Energy/commodity questions: official agency, exchange, benchmark publisher, or report publisher domains.

Use `exclude_domains` to suppress known low-quality or irrelevant domains. Do not combine `include_domains` with `exclude_domains` or `boost_domains`.

## Structured Output with `output_schema`

When you need the API to return structured JSON instead of Markdown prose, pass `output_schema` as a parameter. This is especially useful for GDP research where you want machine-readable tables of country data.

**Constraints:**
- Only supported with `research_effort` values `standard`, `deep`, and `exhaustive`. Sending `output_schema` with `lite` returns `422`.
- The root must be an object with `properties` defined.
- Every object must set `additionalProperties: false`.
- Every property must be listed in `required`.
- Max nesting depth: 5. Max total properties: 100.
- Recursive schemas, `allOf`, `not`, `format`, `pattern`, and most validation keywords are not supported.
- Supported patterns: nested objects, arrays, enums, nested `anyOf`, non-recursive `$defs`/`$ref`.

**When `output_schema` is provided**, `output.content` becomes a JSON object conforming to your schema (with `content_type: "object"`) instead of a Markdown string.

**Example — GDP by country:**

```json
{
  "input": "GDP in 2022 for all EU-27 member states in USD with YoY growth rate",
  "research_effort": "deep",
  "output_schema": {
    "type": "object",
    "properties": {
      "countries": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "country": { "type": "string" },
            "gdp_usd_billions": { "type": "number" },
            "yoy_growth_pct": { "type": "number" },
            "anomaly": { "type": "boolean" }
          },
          "required": ["country", "gdp_usd_billions", "yoy_growth_pct", "anomaly"],
          "additionalProperties": false
        }
      },
      "eu_aggregate_gdp_usd_billions": { "type": "number" },
      "eu_average_growth_pct": { "type": "number" },
      "summary": { "type": "string" }
    },
    "required": ["countries", "eu_aggregate_gdp_usd_billions", "eu_average_growth_pct", "summary"],
    "additionalProperties": false
  }
}
```

**When to use `output_schema`:**
- When the caller needs structured data for downstream computation or rendering (charts, tables, dashboards).
- When the report requires a consistent tabular format across multiple queries.

**When NOT to use `output_schema`:**
- When the user wants a narrative report with inline citations (use default Markdown mode).
- When using `research_effort: "lite"`.

For the full parameter reference including all `source_control` options, `freshness` values, `country` codes, and `output_schema` rules, read the OpenAPI spec at `openapi_research.yaml` in this skill directory.

## Handling Results

The broader orchestrator should:

- Preserve `output.content` and `output.sources` together.
- Never detach a `[[n]]` citation from its source list.
- Use source titles/URLs for traceability, but do not expose internal tool traces unless the product surface explicitly supports that.
- If the finance answer says evidence is insufficient, do not override it with an uncited guess from another branch.
- If the finance agent times out but completed a supported branch, it may return a best-effort partial final answer. Treat it as supported only to the extent its citations and wording support the claim.

## Reliability Notes

The finance research agent is optimized for correctness over speed. It may be expensive relative to simple search because it runs parallel research branches and public-data/web-source verification.

Use it deliberately:

- Good: “Find the exact figure and cite the filing/report.”
- Good: “Verify this macro value against official data.”
- Good: “Resolve which of these conflicting finance values is source-correct.”
- Bad: “Give me a quick opinion on whether to buy this stock.”
- Bad: “Summarize today’s market news” unless exact cited finance evidence is required.

## Failure Policy

If the finance research agent fails or returns insufficient evidence:

- Retry only if the workflow can improve the query, source constraints, or effort level.
- Do not blindly increase effort without narrowing the exact evidence target.
- Consider a second branch that searches known official URLs if the first run lacked source specificity.
- Surface insufficiency honestly when no directly supported answer is available.
