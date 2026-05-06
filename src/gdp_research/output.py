import json
import re
from dataclasses import dataclass, field


@dataclass
class ResearchFinding:
    topic: str
    content: str
    citations: list[dict[str, str]] = field(default_factory=list)


@dataclass
class GDPReport:
    query: str
    findings: list[ResearchFinding] = field(default_factory=list)
    raw_markdown: str = ""

    def to_markdown(self) -> str:
        return self.raw_markdown

    def to_json(self) -> dict:
        return {
            "query": self.query,
            "findings": [
                {
                    "topic": f.topic,
                    "content": f.content,
                    "citations": f.citations,
                }
                for f in self.findings
            ],
            "report_markdown": self.raw_markdown,
        }

    def to_json_string(self) -> str:
        return json.dumps(self.to_json(), indent=2)


def extract_report_from_messages(messages: list, query: str) -> GDPReport:
    """Extract the final report from agent message history."""
    report = GDPReport(query=query)

    for msg in reversed(messages):
        content = msg.content if hasattr(msg, "content") else str(msg)
        if isinstance(content, str) and len(content) > 200:
            report.raw_markdown = content
            report.findings = _parse_findings(content)
            break

    return report


def _parse_findings(markdown: str) -> list[ResearchFinding]:
    """Parse markdown report into structured findings."""
    findings = []
    sections = re.split(r"\n## ", markdown)

    for section in sections[1:]:
        lines = section.strip().split("\n", 1)
        topic = lines[0].strip()
        content = lines[1].strip() if len(lines) > 1 else ""
        citations = _extract_citations(content)
        findings.append(
            ResearchFinding(topic=topic, content=content, citations=citations)
        )

    return findings


def _extract_citations(text: str) -> list[dict[str, str]]:
    """Extract citation references from text.

    Handles both [[n]] (You.com Finance Research API format) and [n] formats.
    """
    citations = []
    source_section = re.search(
        r"###\s*Sources\s*\n(.*)", text, re.DOTALL | re.IGNORECASE
    )
    if source_section:
        for line in source_section.group(1).strip().split("\n"):
            match = re.match(
                r"\[?\[(\d+)\]?\]?\s*(.+?):\s*(https?://\S+)", line
            )
            if match:
                citations.append(
                    {
                        "id": match.group(1),
                        "title": match.group(2).strip(),
                        "url": match.group(3).strip(),
                    }
                )
    return citations
