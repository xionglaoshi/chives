// The dsh profile exposes reasoning, but does not forward pi-ai's serviceTier.
// Apply Codex's native payload hook in this Bot's dsh process, before SSE or WebSocket encoding.
import { createRequire, findPackageJSON } from 'node:module';
import { realpathSync, writeFileSync, renameSync } from 'node:fs';
import { randomUUID } from 'node:crypto';
import { pathToFileURL } from 'node:url';

export const name = 'chives-model-settings';

export async function apply(ctx, config) {
  // ACP restores the session's previous route before discovering its options.
  // Select the connection here so a removed model cannot prevent history from resuming.
  ctx.on('agent/created', ({agent,source}) => {
    if (source !== 'resume' || agent.session.header.origin === 'subagent') return;
    const selected = {provider:config.provider, model:config.model,
      ...(config.reasoningEffort ? {reasoningEffort:config.reasoningEffort} : {})};
    const previous = agent.model.current();
    if (previous?.provider !== selected.provider || previous?.model !== selected.model ||
        previous?.reasoningEffort !== selected.reasoningEffort) agent.model.select(selected);
  });
  if (config.provider !== 'openai-codex' || (!config.fastMode && !config.receiptPath)) return;
  const kernel = createRequire(realpathSync(process.argv[1]));
  const adapter = kernel.resolve('@deepseek-ai/dsh-llm-pi-ai');
  const manifest = findPackageJSON('@earendil-works/pi-ai', pathToFileURL(adapter));
  const { createModels } = await import(new URL('dist/models.js', pathToFileURL(manifest)));
  const prototype = Object.getPrototypeOf(createModels({}));
  const streamSimple = prototype.streamSimple;
  if (typeof streamSimple !== 'function') throw Error('当前 dsh 未提供 Codex 快速模式所需的流接口');
  function configuredStream(model, context, options) {
    if (model.provider !== 'openai-codex' || model.id !== config.model) {
      return streamSimple.call(this, model, context, options);
    }
    let sent;
    return streamSimple.call(this, model, context, {
      ...options,
      async onPayload(payload, target) {
        const body = await options?.onPayload?.(payload, target) ?? payload;
        const request = config.fastMode ? {...body, service_tier:'priority'} : body;
        sent = {requestedModel:request.model,requestedEffort:request.reasoning?.effort??null,requestedTier:request.service_tier??null};
        return request;
      },
      async onProviderStreamEvent(event, target) {
        if (config.receiptPath && sent && event.type === 'response.completed') {
          const response = event.response;
          const receipt = {at:new Date().toISOString(),...sent,model:response.model??null,
            effort:response.reasoning?.effort??null,tier:response.service_tier??null};
          const temporary=config.receiptPath+'.'+randomUUID();
          try {
            writeFileSync(temporary, JSON.stringify(receipt), {mode:0o600});
            renameSync(temporary,config.receiptPath);
          } catch { /* A diagnostic write must not interrupt a completed reply. */ }
        }
        await options?.onProviderStreamEvent?.(event,target);
      },
    });
  }
  ctx.effect(() => {
    prototype.streamSimple = configuredStream;
    return () => { if (prototype.streamSimple === configuredStream) prototype.streamSimple = streamSimple; };
  });
}
