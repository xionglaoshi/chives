/**
 * trading-guard: a native Cordis plugin that gates order-like tools on the
 * `tools/pre-execute` waterfall.
 *
 * Rules:
 *  - read-only paper tools always pass;
 *  - order-like tools whose raw name starts with `paper_` return `ask`, so the
 *    approval service must obtain a one-shot human/answerer approval;
 *  - every other order-like tool returns `deny` (the configured `never` policy).
 *
 * No tool input is rewritten; the hook only allows, asks or denies.
 */

const DEFAULT_ORDER_WORDS = ["place_order", "submit_order", "create_order", "cancel_order", "transfer"];
const DEFAULT_READ_ONLY = ["paper_get_account", "paper_list_orders", "paper_verify_ledger"];

function globToRegExp(pattern) {
  const escaped = String(pattern).replace(/[.+^${}()|[\]\\]/g, "\\$&").replace(/\*/g, ".*").replace(/\?/g, ".");
  return new RegExp(`^${escaped}$`, "i");
}

function rawName(name) {
  const text = String(name || "");
  if (!text.startsWith("mcp__")) return text;
  const parts = text.split("__");
  return parts.length > 2 ? parts.slice(2).join("__") : text;
}

function matchesAny(patterns, raw, full) {
  return patterns.some((pattern) => {
    const regex = globToRegExp(pattern);
    return regex.test(raw) || regex.test(full);
  });
}

function isOrderLike(name, words) {
  const lowered = String(name || "").toLowerCase();
  return words.some((word) => lowered.includes(String(word).toLowerCase()));
}

export const name = "trading-guard";
export const inject = ["tools"];

export function apply(ctx, config = {}) {
  const orderWords = Array.isArray(config.orderWords) && config.orderWords.length > 0 ? config.orderWords : DEFAULT_ORDER_WORDS;
  const readOnly = Array.isArray(config.readOnlyTools) ? config.readOnlyTools : DEFAULT_READ_ONLY;
  const paperPrefix = typeof config.paperPrefix === "string" && config.paperPrefix.length > 0 ? config.paperPrefix : "paper_";
  const nonPaperPolicy = config.nonPaperPolicy === "ask" ? "ask" : "never";
  const askPatterns = Array.isArray(config.askPatterns) ? config.askPatterns : [];
  const askReason = typeof config.askReason === "string" ? config.askReason : "paper order requires one-shot human approval";
  const denyReason = typeof config.denyReason === "string" ? config.denyReason : "trading-guard: non-paper order tools are never allowed";

  ctx.effect(() =>
    ctx.on(
      "tools/pre-execute",
      async (exec, next) => {
        const full = String(exec?.name ?? "");
        const raw = rawName(full);
        if (!full) return next();
        if (readOnly.includes(raw) || readOnly.includes(full)) return next();

        if (isOrderLike(raw, orderWords) || isOrderLike(full, orderWords)) {
          if (raw.startsWith(paperPrefix)) {
            return { kind: "ask", reason: askReason, displayReason: { en: askReason } };
          }
          if (nonPaperPolicy === "never") {
            return { kind: "deny", reason: denyReason };
          }
          return { kind: "ask", reason: askReason, displayReason: { en: askReason } };
        }

        if (matchesAny(askPatterns, raw, full)) {
          return { kind: "ask", reason: askReason, displayReason: { en: askReason } };
        }
        return next();
      },
      { prepend: true },
    ),
  );
}

export const internals = { rawName, isOrderLike, matchesAny, globToRegExp, DEFAULT_ORDER_WORDS };
