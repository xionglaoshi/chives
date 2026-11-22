import askAiPrompts from '../../../../config/ask-ai-prompts.json';

export { askAiPrompts };

export function fillAskPrompt(template: string, values: Record<string, string | number>): string {
  return template.replace(/\{\{([^{}]+)\}\}/g, (slot, key: string) =>
    Object.hasOwn(values, key) ? String(values[key]) : slot
  );
}
