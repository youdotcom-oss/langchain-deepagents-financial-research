import asyncio
import json
import logging
import os
import ssl
from datetime import date, timedelta
from typing import Literal

import httpx

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 5
from deepagents import create_deep_agent
from deepagents.backends.utils import create_file_data
from langchain.tools import tool
from langgraph.checkpoint.memory import MemorySaver

from finance_research.output import FinanceReport, extract_report_from_messages
from finance_research.prompts import PRESETS

# ---------------------------------------------------------------------------
# Tool transport method
# ---------------------------------------------------------------------------
# Set to "http" for direct HTTP calls (recommended — simpler, no MCP overhead)
# Set to "mcp" to use the You.com MCP server via langchain-mcp-adapters
TOOL_TRANSPORT = "http"

# ---------------------------------------------------------------------------
# HTTP transport settings (used when TOOL_TRANSPORT = "http")
# ---------------------------------------------------------------------------
# read=None means no read timeout — the Finance Research API can take 10+ min
# at "exhaustive" effort. Connect timeout stays at 30s for fast failure on
# unreachable servers.
HTTP_API_TIMEOUT = httpx.Timeout(30.0, read=None)

HTTP_ENDPOINT = "https://api.you.com/v1/finance_research"

# ---------------------------------------------------------------------------
# MCP transport settings (used when TOOL_TRANSPORT = "mcp")
# ---------------------------------------------------------------------------
# The MCP server exposes multiple tools; we filter to just "you-finance".
# Note: langchain-mcp-adapters' allowedTools config is CLI-only, so we filter
# manually in Python after calling get_tools().
MCP_SERVER_URL = "https://api.you.com/mcp?tools=you-finance"
MCP_TOOL_NAME = "you-finance"

# Custom httpx timeout for MCP — the default SSE read timeout is 300s which
# is too short for deep/exhaustive research. This factory overrides it.
MCP_HTTP_TIMEOUT = httpx.Timeout(120.0, read=None)


def _mcp_http_client_factory(
    headers: dict[str, str] | None = None,
    timeout: httpx.Timeout | None = None,
    auth: httpx.Auth | None = None,
) -> httpx.AsyncClient:
    """Custom httpx client factory for MCP transport.

    langchain-mcp-adapters passes its own timeout, but the conversion from
    timedelta -> httpx.Timeout doesn't always propagate correctly through the
    MCP SDK's streamable HTTP layer. This factory forces our timeout directly.
    """
    return httpx.AsyncClient(
        headers=headers,
        timeout=MCP_HTTP_TIMEOUT,
        auth=auth,
        follow_redirects=True,
    )


# ---------------------------------------------------------------------------
# Shared config
# ---------------------------------------------------------------------------
SKILLS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "skills",
    "youdotcom-finance-research",
)


def _load_skill_files() -> dict[str, any]:
    """Load all files in the youdotcom-finance-research skill directory."""
    files = {}
    for filename in os.listdir(SKILLS_DIR):
        if filename.startswith("."):
            continue
        filepath = os.path.join(SKILLS_DIR, filename)
        if os.path.isfile(filepath):
            with open(filepath) as f:
                files[f"/skills/youdotcom-finance-research/{filename}"] = (
                    create_file_data(f.read())
                )
    return files


# ---------------------------------------------------------------------------
# HTTP tool implementation
# ---------------------------------------------------------------------------
def _create_you_finance_tool(api_key: str):
    """Create a LangChain tool that calls the You.com Finance Research API via direct HTTP."""

    @tool(parse_docstring=True)
    async def you_finance_research(
        input: str,
        research_effort: Literal["deep", "exhaustive"] = "deep",
    ) -> str:
        """Research financial and macroeconomic topics with cited sources.

        Calls the You.com Finance Research API to get finance-grade research, source-backed numeric answers,
        or exact public/company/macroeconomic evidence.
        Invokes the you-finance MCP tool which internally runs multi-step research,
        consults structured public data (World Bank, IMF, OECD, Eurostat, FRED) as well as licensed private data,
        verifies sources across parallel branches, and returns cited answers with [[n]] source tags.

        Args:
            input: The research question (max 40,000 characters).
            research_effort: How thorough the research should be. lite is fast,
                standard is default, deep is thorough, exhaustive is most complete.
        """
        body = {
            "input": input,
            "research_effort": research_effort,
        }

        headers = {"Content-Type": "application/json", "X-API-Key": api_key}

        last_error = None
        response = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                async with httpx.AsyncClient(timeout=HTTP_API_TIMEOUT) as client:
                    response = await client.post(
                        HTTP_ENDPOINT,
                        headers=headers,
                        json=body,
                    )
                break
            except (ssl.SSLError, httpx.ConnectError, httpx.RemoteProtocolError) as e:
                last_error = e
                if attempt < MAX_RETRIES:
                    wait = RETRY_BACKOFF_SECONDS * attempt
                    logger.warning(
                        "you-finance call failed (attempt %d/%d): %s. Retrying in %ds...",
                        attempt,
                        MAX_RETRIES,
                        e,
                        wait,
                    )
                    await asyncio.sleep(wait)

        if response is None:
            return f"Error: request failed after {MAX_RETRIES} attempts. Last error: {last_error}"

        if response.status_code != 200:
            return f"Error {response.status_code}: {response.text}"

        data = response.json()
        output = data.get("output", {})
        content = output.get("content", "")
        content_type = output.get("content_type", "text")
        sources = output.get("sources", [])

        if content_type == "object":
            result = json.dumps(content, indent=2)
        else:
            result = content

        if sources:
            result += "\n\n### Sources\n"
            for i, src in enumerate(sources, 1):
                title = src.get("title", "Untitled")
                url = src.get("url", "")
                result += f"[[{i}]] {title}: {url}\n"

        return result

    return you_finance_research


# ---------------------------------------------------------------------------
# MCP tool loader
# ---------------------------------------------------------------------------
async def _load_mcp_tools(api_key: str):
    """Load the you-finance tool via MCP transport.

    Returns a tuple of (tools_list, mcp_client). The caller must keep a
    reference to mcp_client for the lifetime of the agent — the MCP session
    closes when the client is garbage collected.
    """
    from langchain_mcp_adapters.client import MultiServerMCPClient

    client = MultiServerMCPClient(
        {
            "ydc-server": {
                "transport": "http",
                "url": MCP_SERVER_URL,
                "headers": {"Authorization": f"Bearer {api_key}"},
                "timeout": timedelta(seconds=600),
                "sse_read_timeout": timedelta(seconds=600),
                "httpx_client_factory": _mcp_http_client_factory,
            }
        }
    )

    all_tools = await client.get_tools()

    # langchain-mcp-adapters' allowedTools is CLI-only, so filter manually
    tools = [t for t in all_tools if t.name == MCP_TOOL_NAME]
    if not tools:
        available = [t.name for t in all_tools]
        raise RuntimeError(
            f"{MCP_TOOL_NAME} tool not found. Available tools: {available}"
        )

    return tools, client


# ---------------------------------------------------------------------------
# Agent factory
# ---------------------------------------------------------------------------
async def create_finance_research_agent(
    preset: str = "gdp",
    output_format: str = "markdown",
    ydc_api_key: str | None = None,
    anthropic_api_key: str | None = None,
):
    """Create a finance research agent with the given preset.

    Args:
        preset: Which research preset to use. One of: "gdp", "software_valuations".
        output_format: "markdown" or "json" for the final report format.
        ydc_api_key: You.com API key. Falls back to YDC_API_KEY env var.
        anthropic_api_key: Anthropic API key. Falls back to ANTHROPIC_API_KEY env var.
    """
    if preset not in PRESETS:
        available = ", ".join(PRESETS.keys())
        raise ValueError(f"Unknown preset '{preset}'. Available: {available}")

    ydc_key = ydc_api_key or os.environ["YDC_API_KEY"]
    if anthropic_api_key:
        os.environ["ANTHROPIC_API_KEY"] = anthropic_api_key

    # --- Choose tool transport ---
    mcp_client = None
    if TOOL_TRANSPORT == "mcp":
        tools, mcp_client = await _load_mcp_tools(ydc_key)
    else:
        tools = [_create_you_finance_tool(ydc_key)]

    # --- Build system prompt from preset ---
    preset_config = PRESETS[preset]
    today = date.today().strftime("%B %d, %Y")
    system_prompt = (
        preset_config["system_prompt"].format(date=today)
        + "\n\n"
        + preset_config["workflow"]
    )

    skill_files = _load_skill_files()

    checkpointer = MemorySaver()

    agent = create_deep_agent(
        model="anthropic:claude-opus-4-7",
        tools=tools,
        system_prompt=system_prompt,
        skills=["/skills/"],
        checkpointer=checkpointer,
    )

    agent._skill_files = skill_files
    agent._output_format = output_format
    agent._preset = preset

    # Keep MCP client alive if using MCP transport
    if mcp_client is not None:
        agent._mcp_client = mcp_client

    return agent


async def run_finance_research(
    query: str,
    preset: str = "gdp",
    output_format: str = "markdown",
    thread_id: str = "finance-research-1",
    ydc_api_key: str | None = None,
    anthropic_api_key: str | None = None,
) -> FinanceReport:
    """Run a finance research query and return a structured report.

    Args:
        query: The research question to investigate.
        preset: Which research preset to use. One of: "gdp", "software_valuations".
        output_format: "markdown" or "json".
        thread_id: Thread ID for conversation state.
        ydc_api_key: You.com API key. Falls back to YDC_API_KEY env var.
        anthropic_api_key: Anthropic API key. Falls back to ANTHROPIC_API_KEY env var.

    Returns:
        A FinanceReport with findings, citations, and formatted output.
    """
    agent = await create_finance_research_agent(
        preset=preset,
        output_format=output_format,
        ydc_api_key=ydc_api_key,
        anthropic_api_key=anthropic_api_key,
    )

    result = await agent.ainvoke(
        {
            "messages": [{"role": "user", "content": query}],
            "files": agent._skill_files,
        },
        config={"configurable": {"thread_id": thread_id}},
    )

    report = extract_report_from_messages(result["messages"], query)

    if output_format == "json":
        print(report.to_json_string())
    else:
        print(report.to_markdown())

    return report
