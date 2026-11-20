import { useEffect, useState } from 'react';
import type { FormEvent, ReactElement } from 'react';

import type { ModelApiDto, ModelProviderDto } from '@chives/server/protocol';

import { clearModelProvider, fetchModelProvider, saveModelProvider } from '../api/client';

const API_LABELS: Record<ModelApiDto, string> = {
  'openai-completions': 'OpenAI Chat Completions',
  'openai-codex-subscription': 'OpenAI · Codex 订阅',
  'openai-responses': 'OpenAI Responses',
  'anthropic-messages': 'Anthropic Messages'
};

interface Draft {
  baseURL: string;
  api: ModelApiDto;
  model: string;
  displayName: string;
  contextWindow: string;
  maxTokens: string;
  deepseekThinking: boolean;
  apiKey: string;
}

function draftOf(dto: ModelProviderDto): Draft {
  return {
    baseURL: dto.baseURL,
    api: dto.api,
    model: dto.model,
    displayName: dto.displayName ?? '',
    contextWindow: dto.contextWindow === undefined ? '' : String(dto.contextWindow),
    maxTokens: dto.maxTokens === undefined ? '' : String(dto.maxTokens),
    deepseekThinking: dto.deepseekThinking,
    apiKey: ''
  };
}

function optionalInt(text: string): number | undefined {
  const trimmed = text.trim();
  return trimmed === '' ? undefined : Number(trimmed);
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/** Endpoint, model and key every bot uses; saving restarts idle bot processes onto it. */
export function ModelProviderForm(): ReactElement {
  const [saved, setSaved] = useState<ModelProviderDto | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetchModelProvider(controller.signal)
      .then((dto) => {
        setSaved(dto);
        setDraft(draftOf(dto));
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) setError(errorText(reason));
      });
    return () => controller.abort();
  }, []);

  if (draft === null) {
    return (
      <div className="settings__row">
        <span className="settings__row-hint">{error ?? '正在读取模型配置…'}</span>
      </div>
    );
  }

  const set = <K extends keyof Draft>(key: K, value: Draft[K]): void => {
    setDraft((current) => (current === null ? current : { ...current, [key]: value }));
    setNotice(null);
  };

  const submit = async (event: FormEvent): Promise<void> => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const contextWindow = optionalInt(draft.contextWindow);
      const maxTokens = optionalInt(draft.maxTokens);
      const next = await saveModelProvider({
        baseURL: draft.baseURL,
        api: draft.api,
        model: draft.model,
        ...(draft.displayName.trim() === '' ? {} : { displayName: draft.displayName.trim() }),
        ...(contextWindow === undefined ? {} : { contextWindow }),
        ...(maxTokens === undefined ? {} : { maxTokens }),
        deepseekThinking: draft.deepseekThinking,
        ...(draft.apiKey.trim() === '' ? {} : { apiKey: draft.apiKey.trim() })
      });
      setSaved(next);
      setDraft(draftOf(next));
      setNotice(
        next.active
          ? '已保存。空闲的 Bot 已重启，正在回答的 Bot 会在这轮结束后切换。'
          : '已保存，但还没有密钥，暂不生效。'
      );
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setBusy(false);
    }
  };

  const reset = async (): Promise<void> => {
    setBusy(true);
    setError(null);
    try {
      const next = await clearModelProvider();
      setSaved(next);
      setDraft(draftOf(next));
      setNotice('已清除，Bot 改回启动脚本里的模型配置。');
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setBusy(false);
    }
  };

  const thinkingApplies = draft.api === 'openai-completions';

  return (
    <form className="settings__row settings__row--stack model-provider" onSubmit={(event) => void submit(event)}>
      <div className="settings__row-text">
        <span className="settings__row-label">模型接入</span>
        <span className="settings__row-hint">
          {saved?.active === true
            ? `生效中：所有 Bot 默认使用 ${saved.displayName ?? saved.model}`
            : '未生效：当前使用启动脚本里的模型配置。填好地址、模型和密钥后保存即可切换。'}
        </span>
      </div>

      <div className="model-provider__grid">
        <label className="model-provider__field model-provider__field--wide">
          <span>API 地址</span>
          <input
            className="settings__input"
            type="url"
            required
            value={draft.baseURL}
            placeholder="https://api.deepseek.com/v1"
            onChange={(event) => set('baseURL', event.target.value)}
          />
        </label>
        <label className="model-provider__field">
          <span>模型 ID</span>
          <input
            className="settings__input"
            required
            value={draft.model}
            placeholder="deepseek-flash"
            onChange={(event) => set('model', event.target.value)}
          />
        </label>
        <label className="model-provider__field">
          <span>显示名称（可选）</span>
          <input
            className="settings__input"
            value={draft.displayName}
            placeholder={draft.model}
            onChange={(event) => set('displayName', event.target.value)}
          />
        </label>
        <label className="model-provider__field">
          <span>API 协议</span>
          <select
            className="settings__select"
            value={draft.api}
            onChange={(event) => set('api', event.target.value as ModelApiDto)}
          >
            {(Object.keys(API_LABELS).filter(api=>api!=='openai-codex-subscription'||draft.api===api) as ModelApiDto[]).map((api) => (
              <option key={api} value={api}>
                {API_LABELS[api]}
              </option>
            ))}
          </select>
        </label>
        <label className="model-provider__field">
          <span>API 密钥</span>
          <input
            className="settings__input"
            type="password"
            autoComplete="off"
            value={draft.apiKey}
            placeholder={saved?.keyConfigured === true ? '已保存，留空不修改' : '未配置'}
            onChange={(event) => set('apiKey', event.target.value)}
          />
        </label>
        <label className="model-provider__field">
          <span>上下文窗口（可选）</span>
          <input
            className="settings__input"
            inputMode="numeric"
            value={draft.contextWindow}
            placeholder="按模型默认"
            onChange={(event) => set('contextWindow', event.target.value)}
          />
        </label>
        <label className="model-provider__field">
          <span>最大输出（可选）</span>
          <input
            className="settings__input"
            inputMode="numeric"
            value={draft.maxTokens}
            placeholder="按模型默认"
            onChange={(event) => set('maxTokens', event.target.value)}
          />
        </label>
      </div>

      <label className="model-provider__check">
        <input
          type="checkbox" role="switch"
          checked={draft.deepseekThinking && thinkingApplies}
          disabled={!thinkingApplies}
          onChange={(event) => set('deepseekThinking', event.target.checked)}
        />
        DeepSeek 思考开关格式（DeepSeek V4 系列经 OpenAI 兼容接口时勾选）
      </label>

      {error === null ? null : (
        <div className="settings__status settings__status--error" role="alert">
          {error}
        </div>
      )}
      {notice === null ? null : <div className="settings__status">{notice}</div>}

      <div className="model-provider__actions">
        <button type="submit" className="settings__button settings__button--primary" disabled={busy}>
          {busy ? '保存中…' : '保存并应用'}
        </button>
        {saved?.active === true || saved?.keyConfigured === true ? (
          <button type="button" className="settings__button" disabled={busy} onClick={() => void reset()}>
            清除，改回启动脚本配置
          </button>
        ) : null}
      </div>
    </form>
  );
}
