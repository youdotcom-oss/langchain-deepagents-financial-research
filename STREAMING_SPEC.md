# Finance Research Agent — SSE Streaming Spec

Spec for a React frontend that consumes a Server-Sent Events stream from the finance research backend deployed on Railway.

---

## 1. Backend overview

The backend is a FastAPI server (`server.py`) that wraps a LangChain Deep Agent. The agent uses Claude claude-opus-4-7, has access to a `you_finance` research tool, and can delegate work to subagents. A single run can take 30 seconds to 10+ minutes depending on query complexity.

**Deployment:** Railway (Docker, `Dockerfile` in repo root)
**Base URL:** set via environment variable, e.g. `NEXT_PUBLIC_API_URL`

---

## 2. API endpoints

### `GET /health`

Returns `{ "status": "ok", "presets": ["gdp", "software_valuations"] }`.
Use this to verify connectivity and populate the preset picker.

### `POST /run`

Starts a research run. Returns an SSE stream (`text/event-stream`).

**Request body (JSON):**

```json
{
  "preset": "gdp",
  "query": "What is Germany's GDP trend over the last 5 years?",
  "output_format": "markdown"
}
```

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `preset` | `"gdp" \| "software_valuations"` | `"gdp"` | Determines the system prompt and workflow |
| `query` | `string` | required | The user's research question |
| `output_format` | `"markdown" \| "json"` | `"markdown"` | Format of the final report |

**Auth (optional):** If `API_SECRET` is set on the backend, send `Authorization: Bearer <secret>`.

---

## 3. SSE event types

The stream emits named SSE events. Each event has `event:` and `data:` lines. The `data:` line is always a JSON object.

Every event's JSON payload includes a `source` field: `"main"` (the primary agent) or `"subagent"` (a delegated child agent).

### 3.1 `status`

Phase transitions for the run lifecycle.

```
event: status
data: {"phase": "creating_agent", "preset": "gdp"}

event: status
data: {"phase": "running", "thread_id": "research-9fd2a461317d"}

event: status
data: {"phase": "complete"}
```

| Field | Type | Values |
|-------|------|--------|
| `phase` | string | `"creating_agent"` → `"running"` → `"complete"` |
| `preset` | string | Present on `creating_agent` only |
| `thread_id` | string | Present on `running` only |

### 3.2 `tool_call`

Emitted when the agent (or a subagent) invokes any tool.

```
event: tool_call
data: {"source": "main", "tool": "you_finance", "label": "Researching finance data", "preview": "What was Germany's nominal GDP in 2024 in USD?"}
```

| Field | Type | Notes |
|-------|------|-------|
| `source` | `"main" \| "subagent"` | Which agent made the call |
| `tool` | string | Raw tool name (e.g. `you_finance`, `write_file`, `task`, `grep`) |
| `label` | string | Human-readable label for UI display (e.g. "Researching finance data", "Writing file") |
| `preview` | string | The most relevant argument — the query for research, file path for file ops, command for execute, etc. |

**Known tool names and labels:**

| `tool` | `label` | What `preview` contains |
|--------|---------|------------------------|
| `you_finance` | Researching finance data | The research query (up to 300 chars) |
| `task` | Delegating to subagent | Subagent task description |
| `write_file` | Writing file | File path |
| `read_file` | Reading file | File path |
| `edit_file` | Editing file | File path |
| `ls` | Listing directory | Directory path |
| `glob` | Searching files | Glob pattern |
| `grep` | Searching content | Search pattern |
| `execute` | Running command | Shell command (up to 200 chars) |
| `write_todos` | Updating task list | JSON of todo args |

### 3.3 `tool_result`

Emitted when any tool returns its result.

```
event: tool_result
data: {"source": "main", "tool": "you_finance", "label": "Researching finance data", "preview": "Germany's nominal GDP in 2024 was **US$4.686 trillion**...", "length": 289}
```

| Field | Type | Notes |
|-------|------|-------|
| `source` | `"main" \| "subagent"` | |
| `tool` | string | Same tool name as the preceding `tool_call` |
| `label` | string | Human-readable label |
| `preview` | string | First 500 chars of the tool's response |
| `length` | number | Full response length in characters |

### 3.4 `thinking`

Emitted when the model produces extended-thinking content (Anthropic only). These are internal reasoning fragments — not part of the final answer.

```
event: thinking
data: {"source": "main", "content": "I need to decompose this into two queries..."}
```

| Field | Type | Notes |
|-------|------|-------|
| `source` | `"main" \| "subagent"` | |
| `content` | string | Fragment of the model's internal reasoning. Arrives in chunks, concatenate them. |

### 3.5 `token`

Streaming text tokens from the model's visible output. These arrive as the model generates — typically 10-50 chars per event.

```
event: token
data: {"source": "main", "content": "Germany's nominal GD"}

event: token
data: {"source": "main", "content": "P in 2024 was approximately **US$4.686 trillion**..."}
```

| Field | Type | Notes |
|-------|------|-------|
| `source` | `"main" \| "subagent"` | |
| `content` | string | Plain text fragment. Concatenate all tokens to build the full response. May contain markdown. |

### 3.6 `report`

Emitted once after the agent finishes. Contains the full final report.

```
event: report
data: {
  "query": "What is Germany GDP in 2024?",
  "markdown": "Germany's nominal GDP in 2024 was **US$4.686 trillion** [[1]].\n\n### Sources\n[[1]] ...",
  "findings": [
    {
      "topic": "Regional Overview",
      "content": "...",
      "citations": [{"id": "1", "title": "...", "url": "https://..."}]
    }
  ]
}
```

| Field | Type | Notes |
|-------|------|-------|
| `query` | string | Echo of the original query |
| `markdown` | string | Complete report as markdown. Render this as the final output. |
| `findings` | array | Structured breakdown by section (may be empty for short answers) |
| `findings[].topic` | string | Section heading |
| `findings[].content` | string | Section body (markdown) |
| `findings[].citations` | array | `{id, title, url}` objects for sources referenced in this section |

### 3.7 `error`

Emitted if the run fails.

```
event: error
data: {"message": "Research run failed: API key invalid"}
```

### 3.8 Keep-alive comments

The server sends SSE comments every 20 seconds during idle periods (e.g. waiting for a long `you_finance` call). These are NOT events — they look like:

```
: keep-alive
```

The browser's `EventSource` API ignores these automatically. If using `fetch()` to parse the stream manually, skip lines starting with `:`.

---

## 4. Event ordering and typical flow

A typical run produces events in this order:

```
status(creating_agent)
status(running)
tool_call(you_finance)       ← agent calls the research API
: keep-alive                 ← server heartbeat during long tool wait
: keep-alive
tool_result(you_finance)     ← research API returns
thinking(...)                ← model reasons about the result (optional, may not appear)
token(...)                   ← model streams its answer
token(...)
token(...)
report(...)                  ← final assembled report
status(complete)
```

For complex queries, the agent may loop multiple times:

```
status(creating_agent)
status(running)
tool_call(write_todos)       ← agent plans its work
tool_result(write_todos)
tool_call(you_finance)       ← first research query (broad)
tool_result(you_finance)
tool_call(you_finance)       ← second research query (targeted follow-up)
tool_result(you_finance)
tool_call(task)              ← delegates deeper analysis to subagent
  tool_call(you_finance)     ← subagent's own research call (source="subagent")
  tool_result(you_finance)
  token(...)                 ← subagent streams its partial answer
tool_result(task)            ← subagent returns its result to main agent
tool_call(write_file)        ← agent writes the report to virtual filesystem
tool_result(write_file)
token(...)                   ← agent streams final summary
report(...)
status(complete)
```

---

## 5. Connecting from React

### Option A: `EventSource` (simplest)

`EventSource` only supports GET. Since `/run` is POST, use `fetch` instead. But if the backend is modified to accept GET with query params, this works:

```js
const es = new EventSource(`${API_URL}/run?preset=gdp&query=...`);
es.addEventListener("tool_call", (e) => { /* JSON.parse(e.data) */ });
es.addEventListener("token", (e) => { /* append to response text */ });
es.addEventListener("report", (e) => { /* show final report */ });
es.addEventListener("error", (e) => { /* handle error */ });
```

### Option B: `fetch` + manual SSE parsing (recommended)

```js
const response = await fetch(`${API_URL}/run`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ preset: "gdp", query: userQuery }),
});

const reader = response.body.getReader();
const decoder = new TextDecoder();
let buffer = "";

while (true) {
  const { done, value } = await reader.read();
  if (done) break;
  buffer += decoder.decode(value, { stream: true });

  // SSE events are separated by double newlines
  const parts = buffer.split("\n\n");
  buffer = parts.pop(); // keep incomplete chunk in buffer

  for (const part of parts) {
    if (!part.trim() || part.startsWith(":")) continue; // skip keep-alive comments

    const eventMatch = part.match(/^event:\s*(.+)$/m);
    const dataMatch = part.match(/^data:\s*(.+)$/m);
    if (!eventMatch || !dataMatch) continue;

    const eventType = eventMatch[1];
    const payload = JSON.parse(dataMatch[1]);

    switch (eventType) {
      case "status":      // update phase indicator
      case "tool_call":   // add to activity feed
      case "tool_result": // update activity feed item
      case "thinking":    // append to thinking display
      case "token":       // append to response text
      case "report":      // render final markdown
      case "error":       // show error state
    }
  }
}
```

### Option C: `@microsoft/fetch-event-source` (recommended for production)

```
npm install @microsoft/fetch-event-source
```

```js
import { fetchEventSource } from "@microsoft/fetch-event-source";

await fetchEventSource(`${API_URL}/run`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ preset, query }),
  onmessage(event) {
    const payload = JSON.parse(event.data);
    switch (event.event) {
      case "tool_call":   // ...
      case "tool_result": // ...
      case "thinking":    // ...
      case "token":       // ...
      case "report":      // ...
      case "status":      // ...
      case "error":       // ...
    }
  },
  onerror(err) { /* handle connection errors, optionally retry */ },
});
```

---

## 6. Suggested UI states

### Phase: Idle
- Show preset picker (`gdp` / `software_valuations`) and query input.
- Hit `GET /health` on mount to verify backend is reachable.

### Phase: Creating Agent (`status.phase === "creating_agent"`)
- Show a spinner with "Initializing research agent..."

### Phase: Running (`status.phase === "running"`)
- Show an **activity feed** that grows as events arrive.
- Each `tool_call` adds a card: icon + `label` text + `preview` as subtitle. Show a spinner on the card.
- Each `tool_result` updates the matching card: replace spinner with checkmark, optionally show `preview` in a collapsible.
- `thinking` events: show in a dimmed/italic collapsible section ("Agent is reasoning..."). Concatenate fragments.
- `token` events: append to a streaming text area below the activity feed. This is the agent's visible response.
- `source === "subagent"` events: indent or badge them differently ("Subagent: ...").

### Phase: Complete (`status.phase === "complete"`)
- Hide the activity feed spinner.
- Replace the streaming text with the rendered `report.markdown` (use a markdown renderer like `react-markdown`).
- Show `report.findings` as structured sections if desired.

### Phase: Error (`error` event)
- Show error banner with `message`.
- Allow retry.

---

## 7. Important implementation notes

1. **Runs can be long.** A `you_finance` call at `exhaustive` effort can take 5-10 minutes. The server sends `: keep-alive` comments every 20s to prevent proxy timeouts. The UI should show the activity feed and heartbeat indicator so users know it's still working.

2. **Token concatenation.** `token` events are fragments. Concatenate `content` fields in order to build the full response. Do NOT replace — append.

3. **Thinking is optional.** The `thinking` event only appears if the model uses Anthropic extended thinking. Don't depend on it being present.

4. **Report vs tokens.** The `report` event contains the canonical final output (extracted from the agent's `write_file` to `/final_report.md`). The concatenated `token` stream is the agent's visible narration, which may be shorter or different from the report. **Always prefer `report.markdown` for the final rendered output.**

5. **Findings may be empty.** For simple one-sentence answers, `report.findings` will be `[]`. The `report.markdown` field always has the full text.

6. **CORS.** The backend allows `*` origins. No special CORS config needed on the frontend.

7. **No retry/reconnect.** Each `/run` call is a one-shot stream. If the connection drops, start a new request. There is no resume mechanism.

8. **Tool call / result pairing.** Tool calls and results arrive in order. A `tool_call` is always followed eventually by a matching `tool_result` with the same `tool` name. But there may be other events (keep-alives, subagent events) in between.

---

## 8. Testing

To manually inspect the SSE stream:

```bash
curl -s -N --no-buffer \
  -X POST https://YOUR_RAILWAY_URL/run \
  -H "Content-Type: application/json" \
  -d '{"preset":"gdp","query":"What is Germany GDP in 2024? One sentence only.","output_format":"markdown"}'
```

This prints raw SSE events as they arrive. A simple query like the above completes in ~30-60 seconds and produces all event types except `thinking` (which requires extended thinking to be enabled on the model).
