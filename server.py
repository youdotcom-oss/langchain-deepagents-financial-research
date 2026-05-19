"""FastAPI streaming server for the finance research agent.

Exposes a POST /run endpoint that accepts a preset + query, runs the Deep Agent,
and streams SSE events back to the client with typed payloads:
  - status:      phase transitions (creating_agent, running, complete)
  - tool_call:   any tool the agent invokes, with a human-readable label + args preview
  - tool_result: any tool result, with a content preview
  - thinking:    Anthropic extended-thinking blocks as they stream
  - token:       streaming LLM text tokens
  - report:      final assembled report (markdown + structured findings)
  - error:       if something fails
"""

import asyncio
import json
import logging
import os
import sys
import uuid
from contextlib import asynccontextmanager

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from finance_research.agent import create_finance_research_agent
from finance_research.output import extract_report_from_messages
from finance_research.prompts import PRESETS

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

API_SECRET = os.environ.get("API_SECRET", "")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Finance Research server starting")
    logger.info("Available presets: %s", list(PRESETS.keys()))
    yield
    logger.info("Finance Research server shutting down")


app = FastAPI(title="Finance Research Agent", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "OPTIONS"],
    allow_headers=["*"],
)


class RunRequest(BaseModel):
    preset: str = "gdp"
    query: str
    output_format: str = "markdown"


def _check_auth(request: Request):
    if not API_SECRET:
        return
    token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if token != API_SECRET:
        raise HTTPException(status_code=401, detail="Invalid API secret")


_TOOL_LABELS: dict[str, str] = {
    "youdotcom-finance-research": "Researching finance data",
    "task": "Delegating to subagent",
    "write_file": "Writing file",
    "read_file": "Reading file",
    "edit_file": "Editing file",
    "ls": "Listing directory",
    "glob": "Searching files",
    "grep": "Searching content",
    "execute": "Running command",
    "write_todos": "Updating task list",
}


def _tool_args_preview(name: str, args: dict) -> str:
    """Return the most human-readable single arg for a tool call."""
    if name in ("youdotcom-finance-research"):
        return args.get("input", "")[:300]
    if name == "task":
        return args.get("description", "")
    if name in ("write_file", "read_file", "edit_file"):
        return args.get("file_path", "") or args.get("path", "")
    if name == "execute":
        return args.get("command", "")[:200]
    if name in ("ls", "glob"):
        return args.get("path", "") or args.get("pattern", "")
    if name == "grep":
        return args.get("pattern", "")
    return json.dumps(args, default=str)[:200]


def _sse_event(event_type: str, data: dict) -> str:
    payload = json.dumps(data, default=str)
    return f"event: {event_type}\ndata: {payload}\n\n"


@app.get("/health")
async def health():
    return {"status": "ok", "presets": list(PRESETS.keys())}


@app.post("/run")
async def run_research(body: RunRequest, request: Request):
    _check_auth(request)

    if body.preset not in PRESETS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown preset '{body.preset}'. Available: {list(PRESETS.keys())}",
        )

    async def event_stream():
        thread_id = f"research-{uuid.uuid4().hex[:12]}"
        all_messages = []
        queue: asyncio.Queue[str | None] = asyncio.Queue()

        async def _produce() -> None:
            try:
                await queue.put(_sse_event("status", {"phase": "creating_agent", "preset": body.preset}))

                agent = await create_finance_research_agent(
                    preset=body.preset,
                    output_format=body.output_format,
                )

                await queue.put(_sse_event("status", {"phase": "running", "thread_id": thread_id}))

                async for chunk in agent.astream(
                    {
                        "messages": [{"role": "user", "content": body.query}],
                        "files": agent._skill_files,
                    },
                    config={"configurable": {"thread_id": thread_id}},
                    stream_mode=["updates", "messages"],
                    subgraphs=True,
                    version="v2",
                ):
                    chunk_type = chunk["type"]
                    ns = chunk["ns"]
                    data = chunk["data"]

                    is_subagent = any(
                        s.startswith("tools:") for s in ns
                    ) if ns else False
                    source = "subagent" if is_subagent else "main"

                    if chunk_type == "updates":
                        for node_name, node_data in data.items():
                            if not node_data:
                                continue
                            messages = node_data.get("messages", [])
                            for msg in messages:
                                all_messages.append(msg)

                                # Emit a tool_call event for every tool the agent invokes
                                tool_calls = getattr(msg, "tool_calls", None)
                                if tool_calls:
                                    for tc in tool_calls:
                                        tc_name = tc.get("name", "")
                                        tc_args = tc.get("args", {})
                                        await queue.put(_sse_event("tool_call", {
                                            "source": source,
                                            "tool": tc_name,
                                            "label": _TOOL_LABELS.get(tc_name, tc_name),
                                            "preview": _tool_args_preview(tc_name, tc_args),
                                        }))

                                # Emit a tool_result event for every tool response
                                if getattr(msg, "type", None) == "tool":
                                    tool_name = getattr(msg, "name", "")
                                    content = getattr(msg, "content", "")
                                    preview = content[:500] if isinstance(content, str) else str(content)[:500]
                                    await queue.put(_sse_event("tool_result", {
                                        "source": source,
                                        "tool": tool_name,
                                        "label": _TOOL_LABELS.get(tool_name, tool_name),
                                        "preview": preview,
                                        "length": len(content) if isinstance(content, str) else 0,
                                    }))

                            await queue.put(_sse_event("step", {
                                "source": source,
                                "node": node_name,
                                "action": "step_complete",
                            }))

                    elif chunk_type == "messages":
                        token, metadata = data
                        raw_content = getattr(token, "content", "")

                        if isinstance(raw_content, list):
                            text = "".join(
                                b.get("text", "") for b in raw_content
                                if isinstance(b, dict) and b.get("type") == "text"
                            )
                            thinking = "".join(
                                b.get("thinking", "") for b in raw_content
                                if isinstance(b, dict) and b.get("type") == "thinking"
                            )
                        else:
                            text = raw_content
                            thinking = ""

                        if getattr(token, "tool_call_chunks", None):
                            continue

                        if getattr(token, "type", "") == "AIMessageChunk":
                            if thinking:
                                await queue.put(_sse_event("thinking", {
                                    "source": source,
                                    "content": thinking,
                                }))
                            if text:
                                await queue.put(_sse_event("token", {
                                    "source": source,
                                    "content": text,
                                }))

                # Stream complete — extract and send the final report
                report = extract_report_from_messages(all_messages, body.query)
                await queue.put(_sse_event("report", {
                    "query": report.query,
                    "markdown": report.raw_markdown,
                    "findings": [
                        {
                            "topic": f.topic,
                            "content": f.content,
                            "citations": f.citations,
                        }
                        for f in report.findings
                    ],
                }))

                await queue.put(_sse_event("status", {"phase": "complete"}))

            except Exception as e:
                logger.exception("Research run failed")
                await queue.put(_sse_event("error", {"message": str(e)}))
            finally:
                await queue.put(None)  # sentinel

        async def _heartbeat() -> None:
            while True:
                await asyncio.sleep(20)
                await queue.put(": keep-alive\n\n")

        producer = asyncio.create_task(_produce())
        heartbeat = asyncio.create_task(_heartbeat())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield item
        finally:
            heartbeat.cancel()
            producer.cancel()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
