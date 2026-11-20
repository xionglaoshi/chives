---
name: run-workflow
description: "Orchestrate parallel subagent pipelines from a JavaScript workflow script. Fan out work across many items (tickers, filings, findings) then synthesize. Uses the dsh workflow tool with a separate meta argument."
---

# Programmatic Workflows (`workflow`)

Use `workflow` when a deterministic pipeline should orchestrate multiple subagents — fan-out research then synthesize, classify then act per item, generate then verify. Use it when the user asked for a workflow or for large multi-agent orchestration, and when the dispatches are data-driven (one per ticker, per filing, per finding). Do NOT use it for a single subagent (use `subagent`) or for code that dispatches nothing (use `bash`).

## The tool call

The dsh tool takes four arguments: `script` (required plain JavaScript body), `meta` (required identity object), `args` (optional JSON input), and `run_in_background` (optional; returns a job id instead of waiting).

```text
workflow(
  script="<plain JavaScript body>",
  meta={ name: "ticker-briefs", description: "Fan out research, synthesize" },
  args={ tickers: ["AAPL", "MSFT"] },
)
```

`meta.name` (short kebab-case) and `meta.description` are required; `meta.whenToUse` and `meta.phases` are optional. `args` is exposed to the script as the `args` global; wrap a bare list in a field so the tool schema stays an object. A body that still contains `export const meta = {...}` is rejected before execution: in dsh the meta block is data passed beside the script, never a statement inside it.

## The script

You write JavaScript (ES2020), not TypeScript. It runs in a confined VM with no filesystem, network, timer, or Node.js APIs — the subagents it dispatches can use tools, the script itself cannot. Top-level `await` and `return` both work, and the `return` value must be JSON-serializable; it becomes the run result. Return a synthesis rather than the raw children: the rendered result is capped, and a clipped object is unparseable.

```js
phase('Research')
const briefSchema = {
  type: 'object',
  properties: { summary: { type: 'string' }, risks: { type: 'array', items: { type: 'string' } } },
  required: ['summary'],
}
```

## Built-ins

- `await agent(prompt, opts?)` — dispatch one subagent, resolve to its result text. The child is a separate agent (the default spawn provider does not inherit this conversation), so it does not see the script or its sibling children; the prompt must carry everything it needs — and its final text is the whole of what comes back. `opts`: `label` (display name), `phase` (progress group), `schema` (object-rooted JSON Schema; the child answers as matching JSON and the resolved value is the **parsed object**, or `null` if it cannot), and the optional LLM route overrides `provider` and `model`. There is no `agentType` option: passing one is a fatal `UNSUPPORTED_OPTION` error, so put the role the child should play in the prompt instead.
- `await pipeline(items, ...stages)` — **the default for multi-stage work.** Each item flows through every stage independently, with NO barrier between stages: item A can be in stage 3 while item B is still in stage 1, so the run costs the slowest single chain rather than the sum of each stage's slowest item. Each stage receives `(prevResult, originalItem, index)`; a throwing stage nulls that item and skips its remaining stages.
- `await parallel(thunks)` — run an array of `() => Promise` thunks concurrently, resolving to results in order; already-started promises (`parallel([agent(...), ...])`) work too. Use it for a single fan-out, or where the next step genuinely needs the whole set at once — dedup across all results, an early exit when the count is zero, one child weighing the others. Needing to `map`/`filter` between stages is not such a case: do that inside a pipeline stage.
- `phase(title)` / `log(message)` — progress markers streamed live to the user.
- `args` — the `args` value passed to `workflow`, verbatim.

Failure semantics:

- A failed slot resolves to **`null`** — the child errored, timed out, or the run had already spent its dispatch cap. Read `null` as "no result from this call", never as "the child ran and found nothing": a run whose children all return `null` has produced nothing, so check before reporting success and write the synthesis to survive partial results.
- A call your script got wrong — an unknown `agent()` option, an unsupported schema, a tripped cap — is a bug rather than a failure, and so is an ordinary typo or a wrong shape handed to a helper. Those end the run with the real error, in a `parallel` slot or a `pipeline` stage too, instead of leaving you a silent list of nulls to explain.

Engine limits are configuration-dependent. The shipped engine defaults are 1000 `agent()` calls per run, 4096 items per `parallel()`/`pipeline()` call, and an automatic concurrency of `min(16, cores - 2)` when `maxConcurrentAgents` is 0; the script's initial synchronous slice is capped at 5000 ms. A deployment may lower any of these, and tripping a cap ends the run.

## Examples

Single fan-out — one dispatch per item, synthesized in JS:

```js
phase('Research')
const briefSchema = {
  type: 'object',
  properties: { summary: { type: 'string' }, risks: { type: 'array', items: { type: 'string' } } },
  required: ['summary'],
}
const results = await parallel(args.tickers.map((t) => () =>
  agent(`Research ${t}: fundamentals, recent news, key risks.`, { label: t, schema: briefSchema })))

phase('Synthesize')
const briefs = {}
const failed = []
results.forEach((r, i) => { if (r !== null) briefs[args.tickers[i]] = r; else failed.push(args.tickers[i]) })
log(`${Object.keys(briefs).length} briefs, ${failed.length} failed`)
return { briefs, failed }
```

Two stages per item, no barrier — a slow filing never holds up the others:

```js
const reviewed = await pipeline(
  args.tickers,
  (ticker) => agent(`Summarize ${ticker}'s latest 10-Q: segment results, guidance changes, new risk language.`,
    { label: ticker, phase: 'Read' }),
  (summary, ticker) => summary === null ? null : agent(
    `Challenge this ${ticker} summary — what does it overstate, omit, or take on trust?\n\n${summary}`,
    { label: `${ticker} review`, phase: 'Challenge' }),
)

log(`${reviewed.filter((r) => r !== null).length}/${args.tickers.length} reviewed`)
return Object.fromEntries(args.tickers.map((t, i) => [t, reviewed[i]]))
```

Set `phase` per dispatch rather than calling `phase()` inside a stage: items run concurrently, so a global marker set mid-pipeline reflects whichever item reached it last. Guard each stage on its input, and test against `null` rather than truthiness — `0`, `false` and `""` are answers a child succeeded with, and `summary && agent(...)` would drop them as failures.

## Reusing a script

dsh's `workflow` tool has **no saved-workflow-by-name parameter** and no `.agents/workflows/` lookup: every call must carry the script body inline. To reuse a workflow, keep the `.js` file in the workspace, read it (with `read` or `bash`), and pass its text as `script`; keep `meta` beside it as a JSON object. `meta.name` is the display identity, not a lookup key.

## Running

`workflow(script=..., meta=..., args=...)` runs in the foreground and returns the script's `return` value when it finishes. Add `run_in_background: true` to register the run as a job and get a job id immediately; the return value arrives with the completion notice, and you read it with `job_output(job_id=...)` (or `job_list` to find the id, `job_kill` to stop it).

For one or two delegations, skip the orchestration and call `subagent(prompt=..., description=...)` directly: it returns a child id immediately and the child's final answer arrives in its completion notice. Use `workflow` only when the fan-out is data-driven and large enough to be worth writing as a script.
