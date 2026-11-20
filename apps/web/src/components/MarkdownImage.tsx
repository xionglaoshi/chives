import { useEffect, useState } from 'react';
import type { ReactElement } from 'react';

import type { DeliverableDto } from '@chives/server/protocol';

import { botFileContentUrl, deliverableContentUrl } from '../api/client';
import { fileName, resolveMarkdownImagePaths } from '../utils/deliverables';
import './MarkdownImage.css';

type LoadState = 'loading' | 'ready' | 'error';

function isHttpSource(src: string): boolean {
  return /^https?:\/\//i.test(src);
}

function isRelativeSource(src: string): boolean {
  return (
    src !== '' &&
    !/^[a-z][a-z0-9+.-]*:/i.test(src) &&
    !src.startsWith('/') &&
    !src.startsWith('#')
  );
}

export interface MarkdownImageProps {
  src: string;
  alt: string | null;
  /** Bot whose workspace relative paths are resolved against. */
  botId?: string | undefined;
  /** Markdown file directory; relative images resolve here before the workspace root. */
  baseDir?: string | undefined;
  /** Deliverable matched by the relative path or by file name. */
  matched?: DeliverableDto | undefined;
  onOpenDeliverable?: ((deliverable: DeliverableDto, trigger: HTMLElement) => void) | undefined;
}

function MissingImage({ name }: { name: string }): ReactElement {
  return (
    <div className="md-image-missing" role="note">
      <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.3">
        <rect x="1.5" y="2.5" width="11" height="9" rx="1.5" />
        <path d="M2.5 9l3-3 2.2 2.2L9.5 6l2 2" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      <span>图片未找到：{name}</span>
    </div>
  );
}

function ExternalImage({ src, alt }: { src: string; alt: string | null }): ReactElement {
  return (
    <a
      className="md-image-external"
      href={src}
      target="_blank"
      rel="noopener noreferrer"
      title={src}
    >
      <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.3">
        <path d="M5.5 3H3v8h8V8.5" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M8 2.5h3.5V6M11.3 2.7L6.8 7.2" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      <span>外链图片{alt === null || alt === '' ? '' : `：${alt}`}</span>
    </a>
  );
}

export function MarkdownImage({
  src,
  alt,
  botId,
  baseDir,
  matched,
  onOpenDeliverable
}: MarkdownImageProps): ReactElement {
  const [state, setState] = useState<LoadState>('loading');
  const [attempt, setAttempt] = useState(0);
  const relative = isRelativeSource(src);
  const candidates = relative ? resolveMarkdownImagePaths(baseDir, src) : [];
  const path = candidates[Math.min(attempt, Math.max(candidates.length - 1, 0))] ?? '';
  const resolved =
    matched !== undefined
      ? deliverableContentUrl(matched.id)
      : botId !== undefined && path !== ''
        ? botFileContentUrl(botId, path)
        : null;
  const name = fileName(path !== '' ? path : src);

  useEffect(() => {
    setAttempt(0);
    setState('loading');
  }, [src, baseDir, botId, matched]);

  if (isHttpSource(src)) return <ExternalImage src={src} alt={alt} />;
  if (resolved === null || state === 'error') return <MissingImage name={name} />;

  const handleError = (): void => {
    if (matched === undefined && attempt + 1 < candidates.length) {
      setAttempt(attempt + 1);
      return;
    }
    setState('error');
  };

  const open = (trigger: HTMLElement): void => {
    if (matched !== undefined && onOpenDeliverable !== undefined) {
      onOpenDeliverable(matched, trigger);
      return;
    }
    window.open(resolved, '_blank', 'noopener,noreferrer');
  };

  return (
    <figure className="md-figure">
      <button
        type="button"
        className="md-figure__button"
        title="查看大图"
        aria-label={`查看大图：${alt === null || alt === '' ? name : alt}`}
        onClick={(event) => open(event.currentTarget)}
      >
        <span className="md-figure__frame">
          {state === 'loading' ? (
            <span className="md-figure__placeholder skeleton" aria-hidden="true" />
          ) : null}
          <img
            className={`md-figure__image${
              state === 'loading' ? ' md-figure__image--loading' : ''
            }`}
            src={resolved}
            alt={alt ?? ''}
            loading="lazy"
            onLoad={() => setState('ready')}
            onError={handleError}
          />
        </span>
      </button>
      {alt === null || alt === '' ? null : <figcaption>{alt}</figcaption>}
    </figure>
  );
}
