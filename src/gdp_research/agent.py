import os
from datetime import date

from deepagents import create_deep_agent
from deepagents.backends.utils import create_file_data
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.checkpoint.memory import MemorySaver

from gdp_research.output import GDPReport, extract_report_from_messages
from gdp_research.prompts import (
    GDP_RESEARCH_PROMPT,
    RESEARCH_WORKFLOW,
)

SKILL_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "skills",
    "you-finance",
    "SKILL.md",
)


def _load_skill_content() -> str:
    with open(SKILL_PATH) as f:
        return f.read()


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
            }
        }
    )

    all_tools = await client.get_tools()
    tools = [t for t in all_tools if t.name == "you-finance"]
    if not tools:
        available = [t.name for t in all_tools]
        raise RuntimeError(
            f"you-finance tool not found. Available tools: {available}"
        )

    today = date.today().strftime("%B %d, %Y")
    system_prompt = GDP_RESEARCH_PROMPT.format(date=today) + "\n\n" + RESEARCH_WORKFLOW

    skill_content = _load_skill_content()
    skill_files = {
        "/skills/you-finance/SKILL.md": create_file_data(skill_content),
    }

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
