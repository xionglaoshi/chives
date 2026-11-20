import { useEffect, useMemo, useRef, useState } from 'react';
import type { ReactElement } from 'react';

import type { BotSummary, DeliverableDto } from '@chives/server/protocol';

import {
  ApiError,
  botFileContentUrl,
  deliverableContentUrl,
  fetchBotFileText,
  fetchDeliverableText,
  revealDeliverable
} from '../api/client';
import { parseCsv, numericColumns } from '../utils/csv';
import { fileName, formatFileSize, workspaceDirectoryOf } from '../utils/deliverables';
import { formatTime } from '../utils/format';
import { Markdown } from './Markdown';
import './DeliverablePreview.css';

export const CSV_PREVIEW_ROWS = 500;

type LoadState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'ready'; text: string }
  | { status: 'error'; message: string };

function isTextPreview(kind: DeliverableDto['kind']): boolean {
  return kind === 'markdown' || kind === 'csv' || kind === 'json' || kind === 'html' || kind === 'code';
}

function CsvTable({ text }: { text: string }): ReactElement {
  const rows = useMemo(() => parseCsv(text), [text]);
  const header = rows[0] ?? [];
  const data = rows.slice(1);
  const visible = data.slice(0, CSV_PREVIEW_ROWS);
  const numeric = numericColumns(visible);
  const width = Math.max(header.length, ...visible.map((row) => row.length));

  return (
    <div className="preview__csv">
      <div className="preview__table-wrap">
        <table className="preview__table">
          <thead>
            <tr>
              {Array.from({ length: width }, (_, index) => (
                <th key={index} className={numeric.has(index) ? 'preview__num' : undefined}>
                  {header[index] ?? ''}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visible.map((row, rowIndex) => (
              <tr key={rowIndex}>
                {Array.from({ length: width }, (_, index) => (
                  <td key={index} className={numeric.has(index) ? 'preview__num' : undefined}>
                    {row[index] ?? ''}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {data.length > CSV_PREVIEW_ROWS ? (
        <p className="preview__note">
          共 {data.length} 行，仅显示前 {CSV_PREVIEW_ROWS} 行
        </p>
      ) : null}
    </div>
  );
}

function JsonPreview({ text }: { text: string }): ReactElement {
  const formatted = useMemo(() => {
    try {
      return JSON.stringify(JSON.parse(text) as unknown, null, 2);
    } catch {
      return text;
    }
  }, [text]);
  return <pre className="preview__code">{formatted}</pre>;
}

function PreviewBody({
  deliverable,
  state,
  contentUrl,
  onReveal,
  onBinaryError
}: {
  deliverable: DeliverableDto;
  state: LoadState;
  contentUrl: string;
  onReveal: () => void;
  onBinaryError: () => void;
}): ReactElement {
  if ((deliverable.kind === 'image' || deliverable.kind === 'pdf') && state.status === 'error') {
    return (
      <div className="preview__unavailable" role="alert">
        <p>{state.message}</p>
        <button type="button" className="preview__button" onClick={onReveal}>
          在访达中显示
        </button>
      </div>
    );
  }
  if (deliverable.kind === 'image') {
    return (
      <div className="preview__image-wrap">
        <img
          className="preview__image"
          src={contentUrl}
          alt={fileName(deliverable.path)}
          onError={onBinaryError}
        />
      </div>
    );
  }
  if (deliverable.kind === 'pdf') {
    return (
      <iframe
        className="preview__pdf"
        title={fileName(deliverable.path)}
        src={contentUrl}
        onError={onBinaryError}
      />
    );
  }
  if (deliverable.kind === 'other') {
    return (
      <div className="preview__unavailable">
        <p>无法预览</p>
        <button type="button" className="preview__button" onClick={onReveal}>
          在访达中显示
        </button>
      </div>
    );
  }
  if (state.status === 'loading') {
    return <div className="preview__status">正在读取文件…</div>;
  }
  if (state.status === 'error') {
    return (
      <div className="preview__unavailable" role="alert">
        <p>{state.message === '文件已不存在' ? state.message : `无法读取文件：${state.message}`}</p>
        <button type="button" className="preview__button" onClick={onReveal}>
          在访达中显示
        </button>
      </div>
    );
  }
  if (state.status !== 'ready') {
    return <div className="preview__status">正在读取文件…</div>;
  }
  if (deliverable.kind === 'markdown') {
    return (
      <div className="preview__markdown">
        <Markdown botId={deliverable.botId} baseDir={workspaceDirectoryOf(deliverable.path)}>
          {state.text}
        </Markdown>
      </div>
    );
  }
  if (deliverable.kind === 'csv') return <CsvTable text={state.text} />;
  if (deliverable.kind === 'json') return <JsonPreview text={state.text} />;
  return <pre className="preview__code">{state.text}</pre>;
}

export interface DeliverablePreviewProps {
  deliverable: DeliverableDto;
  bots: readonly BotSummary[];
  onClose: () => void;
  /** Read text straight from the bot workspace (MAP.md) instead of a deliverable row. */
  workspaceFile?: { botId: string; path: string } | undefined;
}

export function DeliverablePreview({
  deliverable,
  bots,
  onClose,
  workspaceFile
}: DeliverablePreviewProps): ReactElement {
  const [state, setState] = useState<LoadState>({ status: 'idle' });
  const [revealNotice, setRevealNotice] = useState<string | null>(null);
  const closeRef = useRef<HTMLButtonElement | null>(null);
  const bot = bots.find((entry) => entry.id === deliverable.botId);
  const contentUrl =
    workspaceFile === undefined
      ? deliverableContentUrl(deliverable.id)
      : botFileContentUrl(workspaceFile.botId, workspaceFile.path);

  useEffect(() => {
    closeRef.current?.focus();
  }, [deliverable.id]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent): void => {
      if (event.key !== 'Escape') return;
      event.preventDefault();
      onClose();
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  useEffect(() => {
    setRevealNotice(null);
    if (!isTextPreview(deliverable.kind)) {
      setState({ status: 'idle' });
      return;
    }
    const controller = new AbortController();
    setState({ status: 'loading' });
    const request =
      workspaceFile === undefined
        ? fetchDeliverableText(deliverable.id, controller.signal)
        : fetchBotFileText(workspaceFile.botId, workspaceFile.path, controller.signal);
    void request
      .then((text) => {
        if (!controller.signal.aborted) setState({ status: 'ready', text });
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return;
        setState({
          status: 'error',
          message:
            cause instanceof ApiError && cause.status === 404
              ? '文件已不存在'
              : cause instanceof Error
                ? cause.message
                : '读取失败'
        });
      });
    return () => controller.abort();
  }, [deliverable.id, deliverable.kind, workspaceFile?.botId, workspaceFile?.path]);

  useEffect(() => {
    if (deliverable.kind !== 'image' && deliverable.kind !== 'pdf') return;
    const controller = new AbortController();
    setState({ status: 'idle' });
    void fetch(contentUrl, {
      signal: controller.signal,
      headers: { accept: '*/*' }
    })
      .then((response) => {
        if (response.status === 404) {
          setState({ status: 'error', message: '文件已不存在' });
          return;
        }
        if (!response.ok) {
          setState({ status: 'error', message: `无法读取文件（HTTP ${response.status}）` });
          return;
        }
        controller.abort();
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        setState({ status: 'error', message: '无法读取文件' });
      });
    return () => controller.abort();
  }, [contentUrl, deliverable.id, deliverable.kind]);

  const handleBinaryError = (): void => {
    setState({ status: 'error', message: '文件已不存在或无法加载' });
  };

  const handleReveal = (): void => {
    void revealDeliverable(deliverable.id)
      .then(() => setRevealNotice('已在访达中显示'))
      .catch((cause: unknown) => {
        setRevealNotice(cause instanceof Error ? cause.message : '无法在访达中显示');
      });
  };

  return (
    <aside className="preview" aria-label="交付物预览">
      <header className="preview__header">
        <button
          type="button"
          className="preview__back"
          onClick={onClose}
          aria-label="返回"
        >
          ←
        </button>
        <div className="preview__title">
          <h2 className="preview__name" title={deliverable.path}>
            {fileName(deliverable.path)}
          </h2>
          <div className="preview__subtitle">
            {bot?.name ?? deliverable.botId} · {formatTime(deliverable.createdAt)} ·{' '}
            {workspaceFile === undefined
              ? formatFileSize(deliverable.size)
              : workspaceFile.path === 'MAP.md'
                ? '工作目录地图'
                : '工作目录文件'}
          </div>
        </div>
        <div className="preview__actions">
          <button
            type="button"
            className="preview__button"
            disabled
            title="即将支持"
          >
            导出 PDF
          </button>
          <span className="preview__soon">即将支持</span>
          {workspaceFile === undefined ? (
            <button type="button" className="preview__button" onClick={handleReveal}>
              在访达中显示
            </button>
          ) : null}
          <button
            ref={closeRef}
            type="button"
            className="preview__close"
            onClick={onClose}
            aria-label="关闭预览"
          >
            <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.6">
              <path d="M3 3l10 10M13 3L3 13" strokeLinecap="round" />
            </svg>
          </button>
        </div>
      </header>
      {revealNotice !== null ? (
        <div className="preview__notice" role="status">
          {revealNotice}
        </div>
      ) : null}
      <div className="preview__body">
        <PreviewBody
          deliverable={deliverable}
          state={state}
          contentUrl={contentUrl}
          onReveal={handleReveal}
          onBinaryError={handleBinaryError}
        />
      </div>
    </aside>
  );
}
