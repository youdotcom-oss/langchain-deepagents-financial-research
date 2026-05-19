---
name: youdotcom-finance-research
description: Use this skill when the workflow needs finance-grade research, source-backed numeric answers, or exact company, market, or macroeconomic evidence with citations.
allowed-tools: you-finance
---

# Finance Research Agent Orchestration Skill

Use this skill when a broader agentic workflow needs finance-grade research, source-backed numeric answers, or exact public/company/macroeconomic evidence.

## Purpose

The finance research agent is a specialist evidence engine. It is best used as a delegated branch inside a larger workflow when the main agent needs high-confidence finance answers rather than broad conversational search.

Its retrieval index is optimized for financial data: earnings reports, SEC filings, analyst coverage, market data, and financial news. It runs multiple searches, reads through sources, and synthesizes everything into a thorough, well-cited answer.

## When To Use

Use the finance research agent for:

- Public-company filings, annual reports, investor-relations disclosures, earnings metrics, segment tables, contractual obligations, and note-level values.
- Macro questions that need exact country, period, indicator, unit, vintage, or source-family alignment.
- Financial-market and benchmark questions where contract month, instrument, date, field, currency, or unit matters.
- Derived finance calculations where every source input must be retrieved, aligned, and cited before computing.
- Finance answer verification inside a larger agentic plan, especially when another branch produced a plausible but uncited numeric claim.
- Source-constrained finance research where you need evidence from specific domains.

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

## How To Invoke

### Via MCP

The `you-finance` tool is served by the You.com MCP server:

- **URL:** `https://api.you.com/mcp?tools=you-finance`
- **Auth:** `Authorization: Bearer <YDC_API_KEY>`

Call the tool with:

```json
{
  "input": "What was the latest disclosed value of ...?",
  "research_effort": "deep"
}
```

### Via HTTP (direct API call)

**Endpoint:** `POST https://api.you.com/v1/finance_research`  
**Auth header:** `X-API-Key: <YDC_API_KEY>`  
**Content-Type:** `application/json`

Request body:

```json
{
  "input": "What was the latest disclosed value of ...?",
  "research_effort": "deep"
}
```

### Response shape

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

The citation contract is strict: `output.content` uses `[[n]]` tags only. `[[1]]` maps to `output.sources[0]`, `[[2]]` maps to `output.sources[1]`, and so on.

## Orchestration Pattern

For a broader agentic workflow:

1. Classify whether the user question has a finance evidence requirement.
2. Extract the exact checklist: entity, geography, metric, fiscal/calendar period, quarter/month/date, source vintage, unit, scale, currency, stock vs flow, contract month, and output format.
3. Decide the research effort level:
   - `deep` (default): most financial questions, including multi-company comparisons, earnings analysis, and regulatory research.
   - `exhaustive`: complex financial research tasks where highest quality justifies longer latency and higher cost.
4. Run the finance research agent as an evidence branch, not as an unbounded conversational agent.
5. Treat the returned answer as a cited research artifact. Preserve its citations when synthesizing with other branches.
6. If multiple branches disagree, prefer the branch with the most direct primary source and exact period/unit alignment.

## Handling Results

The broader orchestrator should:

- Preserve `output.content` and `output.sources` together.
- Never detach a `[[n]]` citation from its source list.
- Use source titles/URLs for traceability, but do not expose internal tool traces unless the product surface explicitly supports that.
- If the finance answer says evidence is insufficient, do not override it with an uncited guess from another branch.
- If the finance agent times out but completed a supported branch, it may return a best-effort partial final answer. Treat it as supported only to the extent its citations and wording support the claim.

## Reliability Notes

The finance research agent is optimized for correctness over speed. It may be expensive relative to simple search because it runs parallel research branches and multi-source verification.

Use it deliberately:

- Good: "Find the exact figure and cite the filing/report."
- Good: "Verify this macro value against official data."
- Good: "Resolve which of these conflicting finance values is source-correct."
- Bad: "Give me a quick opinion on whether to buy this stock."
- Bad: "Summarize today's market news" unless exact cited finance evidence is required.

## Failure Policy

If the finance research agent fails or returns insufficient evidence:

- Retry only if the workflow can improve the query, source constraints, or effort level.
- Do not blindly increase effort without narrowing the exact evidence target.
- Consider a second branch that searches known official URLs if the first run lacked source specificity.
- Surface insufficiency honestly when no directly supported answer is available.
