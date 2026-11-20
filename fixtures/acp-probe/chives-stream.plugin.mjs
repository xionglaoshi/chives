/**
 * chives-stream: forwards dsh's in-process assistant stream (text / reasoning deltas) to a side channel,
 * because dsh-acp only publishes committed messages. Stdout belongs to ACP, so deltas go to stderr as
 * one tagged NDJSON line each: `@@chives-stream {...}`. Read-only: it never changes agent behaviour.
 */
export const name = "chives-stream";
const TAG = "@@chives-stream ";
export function apply(ctx, config = {}) {
  const out = (obj) => { try { process.stderr.write(TAG + JSON.stringify(obj) + "\n"); } catch { /* never break a turn */ } };
  ctx.on("agent/assistant-stream", ({ agent, frame }) => {
    const base = { session: agent?.session?.id ?? agent?.id ?? null, agent: agent?.id ?? null };
    if (frame.type === "start" || frame.type === "end") { out({ ...base, t: frame.type, keys: Object.keys(frame) }); return; }
    const chunk = frame.chunk;
    if (!chunk) return;
    if (chunk.type === "text-delta" || chunk.type === "reasoning-delta") out({ ...base, t: chunk.type, i: chunk.index, text: chunk.text });
    else if (config.verbose) out({ ...base, t: chunk.type });
  });
}
