import { cloneElement, isValidElement } from 'react';
import type { ReactElement, ReactNode } from 'react';
import ReactMarkdown, { type Components } from 'react-markdown';
import remarkCjkFriendly from 'remark-cjk-friendly';
import remarkGfm from 'remark-gfm';

import type { DeliverableDto } from '@chives/server/protocol';

import { fileName, normalizeDeliverablePath } from '../utils/deliverables';
import { MarkdownImage } from './MarkdownImage';
import './Markdown.css';

const NUMERIC = /^[+\-−]?[\d,]+(?:\.\d+)?(?:\s*(?:%|％|元|倍|万|亿|股|手|天|年|份|个))?(?:\s*[▲▼]\s*[\d.,]+%?)?$/;

const SIGNED_PERCENT = /(?<![\w.])[+\-−]\s?\d{1,3}(?:,\d{3})*(?:\.\d+)?\s*%/g;
const SIGNED_PERCENT_EXACT = /^[+\-−]\s?\d{1,3}(?:,\d{3})*(?:\.\d+)?\s*%$/;

function textOf(children: ReactNode): string {
  if (typeof children === 'string' || typeof children === 'number') return String(children);
  if (Array.isArray(children)) return children.map(textOf).join('');
  if (isValidElement(children)) {
    return textOf((children.props as { children?: ReactNode }).children);
  }
  return '';
}

export function isNumericText(value: string): boolean {
  const trimmed = value.trim();
  if (trimmed === '' || trimmed === '—' || trimmed === '-') return false;
  return NUMERIC.test(trimmed);
}

/** `+3.34%`, `−9.05%` and `-0.12%` are signed percentages; `3%` and `+1.2 元` are not. */
export function isSignedPercent(value: string): boolean {
  return SIGNED_PERCENT_EXACT.test(value.trim());
}

function percentClass(token: string): string | null {
  if (!isSignedPercent(token)) return null;
  const numeric = Number(token.replace(/[+\-−%,\s]/g, ''));
  if (!Number.isFinite(numeric) || numeric === 0) return 'md-flat';
  return token.trim().startsWith('+') ? 'md-up' : 'md-down';
}

function colorizeText(text: string): ReactNode {
  const parts: ReactNode[] = [];
  let last = 0;
  for (const match of text.matchAll(SIGNED_PERCENT)) {
    const index = match.index ?? 0;
    if (index > last) parts.push(text.slice(last, index));
    const token = match[0];
    const tone = percentClass(token);
    parts.push(
      tone === null ? (
        token
      ) : (
        <span className={tone} key={`${index}-${token}`}>
          {token}
        </span>
      )
    );
    last = index + token.length;
  }
  if (last === 0) return text;
  if (last < text.length) parts.push(text.slice(last));
  return parts;
}

/** Colours signed percentages in inline text without touching code or links. */
export function colorizePercents(node: ReactNode): ReactNode {
  if (typeof node === 'string') return colorizeText(node);
  if (Array.isArray(node)) return node.map((child) => colorizePercents(child));
  if (isValidElement(node)) {
    if (typeof node.type !== 'string') return node;
    if (node.type === 'code' || node.type === 'a' || node.type === 'button') return node;
    const props = node.props as { children?: ReactNode };
    if (props.children === undefined) return node;
    return cloneElement(
      node as ReactElement<{ children?: ReactNode }>,
      undefined,
      colorizePercents(props.children)
    );
  }
  return node;
}

export function matchDeliverable(
  href: string,
  deliverables: readonly DeliverableDto[]
): DeliverableDto | undefined {
  const target = normalizeDeliverablePath(href);
  const exact = deliverables.find((entry) => normalizeDeliverablePath(entry.path) === target);
  if (exact !== undefined) return exact;
  if (target.includes('/')) return undefined;
  return deliverables.find((entry) => fileName(entry.path) === target);
}

/**
 * An image path may belong to a delegated child workspace, so after the exact
 * match it falls back to a unique image file name inside the task's deliverables.
 */
export function matchImageDeliverable(
  src: string,
  deliverables: readonly DeliverableDto[]
): DeliverableDto | undefined {
  if (!isRelativeHref(src)) return undefined;
  const direct = matchDeliverable(src, deliverables);
  if (direct?.kind === 'image') return direct;
  const target = normalizeDeliverablePath(src);
  if (target === '') return undefined;
  const name = fileName(target);
  return deliverables.find((entry) => entry.kind === 'image' && fileName(entry.path) === name);
}

function isRelativeHref(href: string): boolean {
  return (
    href !== '' &&
    !/^[a-z][a-z0-9+.-]*:/i.test(href) &&
    !href.startsWith('/') &&
    !href.startsWith('#')
  );
}

function isHttpHref(href: string): boolean {
  return /^https?:\/\//i.test(href);
}

type PseudoHeading = 'title' | 'lead' | undefined;

function pseudoHeadingOf(children: ReactNode): PseudoHeading {
  const nodes = (Array.isArray(children) ? children : [children]).filter(
    (node) => !(typeof node === 'string' && node.trim() === '')
  );
  const first = nodes[0];
  if (nodes.length === 1 && isValidElement(first) && first.type === 'strong') return 'title';
  if (isValidElement(first) && first.type === 'strong') {
    const strongText = textOf((first.props as { children?: ReactNode }).children);
    if (/[：:]\s*$/.test(strongText)) return 'lead';
  }
  return undefined;
}

function FilePillIcon(): ReactElement {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.2">
      <path d="M3 1.5h3.8L9 3.7v6.8H3z" strokeLinejoin="round" />
      <path d="M6.5 1.8V4h2.2" strokeLinejoin="round" />
    </svg>
  );
}

export interface MarkdownProps {
  children: string;
  /** Bot whose workspace relative image paths are read from. */
  botId?: string | undefined;
  /** Directory of the Markdown file, so images resolve next to it before the root. */
  baseDir?: string | undefined;
  /** Deliverables a relative link may point at, in the current bot's timeline. */
  deliverables?: readonly DeliverableDto[];
  onOpenDeliverable?: ((deliverable: DeliverableDto, trigger: HTMLElement) => void) | undefined;
}

export function Markdown({
  children,
  botId,
  baseDir,
  deliverables = [],
  onOpenDeliverable
}: MarkdownProps): ReactElement {
  const components: Components = {
    table: ({ children: rows }) => (
      <div className="md-table-wrap">
        <table>{rows}</table>
      </div>
    ),
    th: ({ children: head }) => <th>{head}</th>,
    td: ({ children: cells }) => {
      const numeric = isNumericText(textOf(cells));
      return <td className={numeric ? 'md-num' : undefined}>{colorizePercents(cells)}</td>;
    },
    p: ({ node, children: content }) => {
      // Images render as <figure>, which may not sit inside <p>.
      const hasImage = (node?.children ?? []).some(
        (child) => child.type === 'element' && child.tagName === 'img'
      );
      if (hasImage) return <div className="md-p">{colorizePercents(content)}</div>;
      const pseudo = pseudoHeadingOf(content);
      const className =
        pseudo === 'title'
          ? 'md-pseudo-heading'
          : pseudo === 'lead'
            ? 'md-pseudo-lead'
            : undefined;
      return <p className={className}>{colorizePercents(content)}</p>;
    },
    li: ({ children: content }) => <li>{colorizePercents(content)}</li>,
    a: ({ href, children: label }) => {
      const target = href ?? '';
      if (isHttpHref(target)) {
        return (
          <a href={target} target="_blank" rel="noopener noreferrer">
            {label}
          </a>
        );
      }
      if (isRelativeHref(target)) {
        const matched = matchDeliverable(target, deliverables);
        if (matched !== undefined && onOpenDeliverable !== undefined) {
          return (
            <button
              type="button"
              className="md-deliverable-link"
              onClick={(event) => onOpenDeliverable(matched, event.currentTarget)}
            >
              <FilePillIcon />
              <span className="md-deliverable-link__label">{label}</span>
            </button>
          );
        }
      }
      return <code className="md-link-literal">{label}</code>;
    },
    img: ({ src, alt }) => (
      <MarkdownImage
        src={typeof src === 'string' ? src : ''}
        alt={alt ?? null}
        botId={botId}
        baseDir={baseDir}
        matched={matchImageDeliverable(typeof src === 'string' ? src : '', deliverables)}
        onOpenDeliverable={onOpenDeliverable}
      />
    ),
    pre: ({ children: block }) => <pre className="md-pre">{block}</pre>,
    code: ({ className, children: codeText }) => (
      <code className={className === undefined ? 'md-inline-code' : `md-code ${className}`}>
        {codeText}
      </code>
    )
  };

  return (
    <div className="markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkCjkFriendly]}
        components={components}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
