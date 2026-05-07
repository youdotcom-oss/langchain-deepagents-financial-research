import os
from datetime import date, timedelta

import httpx
from deepagents import create_deep_agent
from deepagents.backends.utils import create_file_data
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.checkpoint.memory import MemorySaver

MCP_TIMEOUT = httpx.Timeout(120.0, read=600.0)


def _mcp_http_client_factory(
    headers: dict[str, str] | None = None,
    timeout: httpx.Timeout | None = None,
    auth: httpx.Auth | None = None,
) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers=headers,
        timeout=MCP_TIMEOUT,
        auth=auth,
        follow_redirects=True,
    )


from gdp_research.output import GDPReport, extract_report_from_messages
from gdp_research.prompts import (
    GDP_RESEARCH_PROMPT,
    RESEARCH_WORKFLOW,
)

SKILLS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "skills",
    "you-finance",
)


def _load_skill_files() -> dict[str, any]:
    """Load all files in the you-finance skill directory."""
    files = {}
    for filename in os.listdir(SKILLS_DIR):
        filepath = os.path.join(SKILLS_DIR, filename)
        if os.path.isfile(filepath):
            with open(filepath) as f:
                files[f"/skills/you-finance/{filename}"] = create_file_data(f.read())
    return files


async def create_gdp_research_agent(
    output_format: str = "markdown",
    ydc_api_key: str | None = None,
    anthropic_api_key: str | None = None,
):
    """Create a GDP macroeconomic research agent.

    Args:
        output_format: "markdown" or "json" for the final report format.
        ydc_api_key: You.com API key. Falls back to YDC_API_KEY env var.
        anthropic_api_key: Anthropic API key. Falls back to ANTHROPIC_API_KEY env var.

    Returns:
        A tuple of (agent, mcp_client) — keep a reference to mcp_client
        for the lifetime of the agent.
    """
    ydc_key = ydc_api_key or os.environ["YDC_API_KEY"]
    if anthropic_api_key:
        os.environ["ANTHROPIC_API_KEY"] = anthropic_api_key

    client = MultiServerMCPClient(
        {
            "ydc-server": {
                "transport": "http",
                "url": "https://api.you.com/mcp",
                "headers": {"Authorization": f"Bearer {ydc_key}"},
                "timeout": timedelta(seconds=120),
                "sse_read_timeout": timedelta(seconds=600),
                "httpx_client_factory": _mcp_http_client_factory,
            }
        }
    )

    all_tools = await client.get_tools()
    tools = [t for t in all_tools if t.name == "you-finance"]
    if not tools:
        available = [t.name for t in all_tools]
        raise RuntimeError(f"you-finance tool not found. Available tools: {available}")

    today = date.today().strftime("%B %d, %Y")
    system_prompt = GDP_RESEARCH_PROMPT.format(date=today) + "\n\n" + RESEARCH_WORKFLOW

    skill_files = _load_skill_files()

    checkpointer = MemorySaver()

    agent = create_deep_agent(
        model="anthropic:claude-sonnet-4-6",
        tools=tools,
        system_prompt=system_prompt,
        skills=["/skills/"],
        checkpointer=checkpointer,
    )

    agent._gdp_skill_files = skill_files
    agent._gdp_output_format = output_format
    agent._mcp_client = client

    return agent


async def run_gdp_research(
    query: str,
    output_format: str = "markdown",
    thread_id: str = "gdp-research-1",
    ydc_api_key: str | None = None,
    anthropic_api_key: str | None = None,
) -> GDPReport:
    """Run a GDP research query and return a structured report.

    Args:
        query: The research question to investigate.
        output_format: "markdown" or "json".
        thread_id: Thread ID for conversation state.
        ydc_api_key: You.com API key. Falls back to YDC_API_KEY env var.
        anthropic_api_key: Anthropic API key. Falls back to ANTHROPIC_API_KEY env var.

    Returns:
        A GDPReport with findings, citations, and formatted output.
    """
    agent = await create_gdp_research_agent(
        output_format=output_format,
        ydc_api_key=ydc_api_key,
        anthropic_api_key=anthropic_api_key,
    )

    result = await agent.ainvoke(
        {
            "messages": [{"role": "user", "content": query}],
            "files": agent._gdp_skill_files,
        },
        config={"configurable": {"thread_id": thread_id}},
    )

    report = extract_report_from_messages(result["messages"], query)

    if output_format == "json":
        print(report.to_json_string())
    else:
        print(report.to_markdown())

    return report
