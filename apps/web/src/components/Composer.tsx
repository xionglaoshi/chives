import { useEffect, useRef, useState } from 'react';
import type { ChangeEvent, ClipboardEvent, KeyboardEvent, ReactElement } from 'react';

import type { MessageAttachmentDto } from '@chives/server/protocol';

import { botFileContentUrl } from '../api/client';
import { formatFileSize } from '../utils/deliverables';
import { ComposerModelPicker } from './ComposerModelPicker';
import './Composer.css';

const ACCEPTED_TYPES =
  '.pdf,.md,.txt,.csv,.tsv,.json,.xlsx,.xls,.docx,.pptx,.png,.jpg,.jpeg,.webp,.gif';

export interface ComposerProps {
  value: string;
  onChange: (value: string) => void;
  onSend: (text: string) => void;
  onStop: () => void;
  running: boolean;
  sending: boolean;
  notice: string | null;
  placeholder?: string;
  autoFocus?: boolean;
  showHint?: boolean;
  /** Increment to move focus back into the textarea (e.g. after reopening a task). */
  focusToken?: number;
  /** Blocks sending while the server is unreachable. */
  disabled?: boolean;
  disabledReason?: string;
  /** Bot whose workspace holds the pending uploads. */
  botId?: string;
  attachments?: readonly MessageAttachmentDto[];
  onAddFiles?: (files: File[]) => void;
  onRemoveAttachment?: (path: string) => void;
  uploading?: boolean;
  suggesting?: boolean;
  suggestion?: string | null;
  uploadNotice?: string | null;
}

function AttachmentIcon({ kind }: { kind: MessageAttachmentDto['kind'] }): ReactElement {
  if (kind === 'image') {
    return (
      <svg width="15" height="15" viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.4">
        <rect x="2" y="3" width="12" height="10" rx="1.5" />
        <circle cx="6" cy="6.5" r="1.2" />
        <path d="M3.5 12l3.5-3.5 2.5 2.5 2-2 2 3" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    );
  }
  return (
    <svg width="15" height="15" viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.4">
      <path d="M4 2h5l3 3v9H4z" strokeLinejoin="round" />
      <path d="M9 2v3h3" strokeLinejoin="round" />
    </svg>
  );
}

function AttachmentChips({
  attachments,
  botId,
  onRemove
}: {
  attachments: readonly MessageAttachmentDto[];
  botId: string | undefined;
  onRemove: ((path: string) => void) | undefined;
}): ReactElement | null {
  if (attachments.length === 0) return null;
  return (
    <ul className="composer__attachments" aria-label="待发送附件">
      {attachments.map((attachment) => (
        <li className="composer__attachment" key={attachment.path}>
          {attachment.kind === 'image' && botId !== undefined ? (
            <img
              className="composer__attachment-thumb"
              src={botFileContentUrl(botId, attachment.path)}
              alt=""
            />
          ) : (
            <span className="composer__attachment-icon" aria-hidden="true">
              <AttachmentIcon kind={attachment.kind} />
            </span>
          )}
          <span className="composer__attachment-name" title={attachment.name}>
            {attachment.name}
          </span>
          <span className="composer__attachment-size">{formatFileSize(attachment.size)}</span>
          <button
            type="button"
            className="composer__attachment-remove"
            aria-label={`移除 ${attachment.name}`}
            onClick={() => onRemove?.(attachment.path)}
          >
            ×
          </button>
        </li>
      ))}
    </ul>
  );
}

export function Composer({
  value,
  onChange,
  onSend,
  onStop,
  running,
  sending,
  notice,
  placeholder = '问点什么，或直接说要做的事',
  autoFocus = false,
  showHint = true,
  focusToken,
  disabled = false,
  disabledReason,
  botId,
  attachments = [],
  onAddFiles,
  onRemoveAttachment,
  uploading = false,
  suggesting = false,
  suggestion = null,
  uploadNotice = null
}: ComposerProps): ReactElement {
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [multiline, setMultiline] = useState(false);

  useEffect(() => {
    const element = textareaRef.current;
    if (element === null) return;
    element.style.height = 'auto';
    const computedLineHeight = Number.parseFloat(getComputedStyle(element).lineHeight);
    const lineHeight = Number.isFinite(computedLineHeight) && computedLineHeight > 0 ? computedLineHeight : 22;
    const maxHeight = Math.round(lineHeight * 8 + 12);
    const height = Math.min(Math.max(34, element.scrollHeight), maxHeight);
    element.style.height = `${height}px`;
    element.style.overflowY = element.scrollHeight > maxHeight ? 'auto' : 'hidden';
    setMultiline(element.scrollHeight > 34 || value.includes('\n'));
  }, [value, suggestion]);

  useEffect(() => {
    if (autoFocus) textareaRef.current?.focus();
  }, [autoFocus]);

  useEffect(() => {
    if (focusToken !== undefined && focusToken > 0) textareaRef.current?.focus();
  }, [focusToken]);

  const submit = (): void => {
    const text = value.trim();
    if ((text === '' && attachments.length === 0) || sending || uploading || disabled) return;
    onSend(text);
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>): void => {
    if (event.key === 'Tab' && !event.shiftKey && !event.nativeEvent.isComposing && suggestion && value === '') {
      event.preventDefault();
      onChange(suggestion);
      return;
    }
    if (event.key !== 'Enter' || event.shiftKey || event.nativeEvent.isComposing) return;
    event.preventDefault();
    submit();
  };

  const handleFileChange = (event: ChangeEvent<HTMLInputElement>): void => {
    const files = Array.from(event.target.files ?? []);
    event.target.value = '';
    if (files.length > 0) onAddFiles?.(files);
  };

  const handlePaste = (event: ClipboardEvent<HTMLTextAreaElement>): void => {
    const clipboard = event.clipboardData;
    let pasted = Array.from(clipboard?.files ?? []);
    if (pasted.length === 0) {
      pasted = Array.from(clipboard?.items ?? [])
        .filter((item) => item.kind === 'file')
        .map((item) => item.getAsFile())
        .filter((file): file is File => file !== null);
    }
    const files = pasted.filter((file) => file.type.startsWith('image/'));
    if (files.length === 0) return;
    event.preventDefault();
    onAddFiles?.(files);
  };

  const sendDisabled = (value.trim() === '' && attachments.length === 0) || sending || uploading || disabled;

  return (
    <div className="composer">
      {uploadNotice === null ? null : (
        <div className="composer__notice composer__notice--upload" role="alert">
          {uploadNotice}
        </div>
      )}
      <AttachmentChips attachments={attachments} botId={botId} onRemove={onRemoveAttachment} />
      <form
        className={`composer__form${multiline ? ' composer__form--multiline' : ''}${
          uploading ? ' composer__form--uploading' : ''
        }`}
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <label className="sr-only" htmlFor="chives-composer">
          给 Bot 发消息
        </label>
        <input
          ref={fileInputRef}
          className="composer__file-input"
          type="file"
          multiple
          accept={ACCEPTED_TYPES}
          aria-hidden="true"
          tabIndex={-1}
          onChange={handleFileChange}
        />
        <button
          type="button"
          className="composer__add"
          aria-label="上传文件"
          title="上传文件（可多选）"
          disabled={disabled || uploading}
          onClick={() => fileInputRef.current?.click()}
        >
          {uploading ? (
            <span className="composer__spinner" aria-hidden="true" />
          ) : (
            <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.6">
              <path d="M8 3v10M3 8h10" strokeLinecap="round" />
            </svg>
          )}
        </button>
        <textarea
          id="chives-composer"
          ref={textareaRef}
          className={suggesting ? "composer__input composer__input--suggesting" : "composer__input"}
          rows={1}
          value={value}
          placeholder={suggesting ? "Chives正在思考您可能想问什么……" : suggestion ?? placeholder}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={handleKeyDown}
          onPaste={handlePaste}
          autoFocus={autoFocus}
          disabled={disabled}
          aria-describedby={disabled ? 'chives-composer-disabled' : undefined}
        />
        {botId && <ComposerModelPicker key={botId} botId={botId} running={running} disabled={disabled || sending}/>}
        {running && !sendDisabled && <button type="submit" className="composer__send" aria-label="提交后续消息">↑</button>}
        {running ? (
          <button type="button" className="composer__stop" onClick={onStop} aria-label="停止当前任务">
            <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
              <rect x="1.5" y="1.5" width="9" height="9" rx="2" fill="currentColor" />
            </svg>
          </button>
        ) : (
          <button
            type="submit"
            className="composer__send"
            aria-label="发送"
            disabled={sendDisabled}
          >
            <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.8">
              <path d="M9 14V4M4.5 8.5L9 4l4.5 4.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
        )}
        {suggestion && value === '' && (
          <button type="button" className="composer__accept-suggestion" onClick={() => {
            onChange(suggestion);
            textareaRef.current?.focus();
          }}>使用建议</button>
        )}
      </form>
      {notice === null ? null : (
        <div className="composer__notice" role="alert">
          {notice}
        </div>
      )}
      {disabled ? (
        <div className="composer__notice" id="chives-composer-disabled" role="status">
          {disabledReason ?? '暂时不能发送消息。'}
        </div>
      ) : null}
      {showHint && !disabled ? (
        <div className="composer__hint">不需要新建对话，Chives 会自己整理上下文。Enter 发送，Shift+Enter 换行。</div>
      ) : null}
    </div>
  );
}
