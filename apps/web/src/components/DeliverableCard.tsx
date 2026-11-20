import { useState } from 'react';
import type { MouseEvent, ReactElement } from 'react';

import type { BotSummary, DeliverableDto, DeliverableKind, MessageDto } from '@chives/server/protocol';

import {
  KIND_LABELS,
  deliverablesFromMessage,
  fileName,
  formatFileSize,
  normalizeDeliverablePath
} from '../utils/deliverables';
import './DeliverableCard.css';

const KIND_PATHS: Record<DeliverableKind, string> = {
  markdown: 'M4 2h7l3 3v11H4zM6.5 8h5M6.5 11h5',
  image: 'M2 15h14M3 12l4-4 3 2 5-6',
  csv: 'M4 2h7l3 3v11H4zM6 7h6M6 10h6M6 13h4',
  json: 'M7 3H5v12h2M11 3h2v12h-2',
  html: 'M3 3h12l-1.5 12L9 17l-4.5-2zM6 6h6M6 9h6',
  pdf: 'M4 2h7l3 3v11H4zM6 9h6M6 12h4',
  code: 'M6 5L2 9l4 4M12 5l4 4-4 4',
  other: 'M4 2h7l3 3v11H4z'
};

function KindIcon({ kind }: { kind: DeliverableKind }): ReactElement {
  return (
    <svg
      className="deliverable-card__icon"
      width="18"
      height="18"
      viewBox="0 0 18 18"
      aria-hidden="true"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.4"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d={KIND_PATHS[kind]} />
    </svg>
  );
}

export interface DeliverableCardProps {
  deliverable: DeliverableDto;
  botName: string;
  delegated: boolean;
  active: boolean;
  onOpen: (deliverable: DeliverableDto, trigger: HTMLElement) => void;
}

export function DeliverableCard({
  deliverable,
  botName,
  delegated,
  active,
  onOpen
}: DeliverableCardProps): ReactElement {
  const kindLabel = KIND_LABELS[deliverable.kind];
  const attribution = delegated ? `由 ${botName} 产出` : botName;
  const handleClick = (event: MouseEvent<HTMLButtonElement>): void => {
    onOpen(deliverable, event.currentTarget);
  };

  return (
    <button
      type="button"
      className={`deliverable-card${active ? ' deliverable-card--active' : ''}`}
      onClick={handleClick}
      aria-current={active ? 'true' : undefined}
      aria-label={`${fileName(deliverable.path)}，${kindLabel}，${attribution}，${formatFileSize(deliverable.size)}`}
      title={deliverable.path}
    >
      <KindIcon kind={deliverable.kind} />
      <span className="deliverable-card__body">
        <span className="deliverable-card__name">{fileName(deliverable.path)}</span>
        <span className="deliverable-card__meta">
          {kindLabel} · {attribution}
        </span>
      </span>
      <span className="deliverable-card__size">{formatFileSize(deliverable.size)}</span>
      {active ? <span className="deliverable-card__state">正在预览</span> : null}
    </button>
  );
}

export interface DeliverableCardsProps {
  message: MessageDto;
  bots: readonly BotSummary[];
  activeId: string | null;
  onOpen: (deliverable: DeliverableDto, trigger: HTMLElement) => void;
  /** Images already shown inline in this turn's Markdown; the cards omit them. */
  embeddedImages?: ReadonlySet<string> | undefined;
}

export const COLLAPSED_DELIVERABLE_COUNT = 4;

export function DeliverableCards({
  message,
  bots,
  activeId,
  onOpen,
  embeddedImages
}: DeliverableCardsProps): ReactElement | null {
  const [expanded, setExpanded] = useState(false);
  const all = deliverablesFromMessage(message);
  const deliverables =
    embeddedImages === undefined || embeddedImages.size === 0
      ? all
      : all.filter(
          (entry) =>
            !(
              entry.kind === 'image' &&
              embeddedImages.has(normalizeDeliverablePath(entry.path))
            )
        );
  if (deliverables.length === 0) return null;

  const delegated = message.meta?.['delegated'] === true;
  const visible =
    expanded || deliverables.length <= COLLAPSED_DELIVERABLE_COUNT
      ? deliverables
      : deliverables.slice(0, COLLAPSED_DELIVERABLE_COUNT);
  const hiddenCount = deliverables.length - visible.length;
  const overflow = message.meta?.['overflow'];

  return (
    <section className="deliverables" aria-label="交付物">
      {visible.map((deliverable) => {
        const bot = bots.find((entry) => entry.id === deliverable.botId);
        return (
          <DeliverableCard
            key={deliverable.id}
            deliverable={deliverable}
            botName={bot?.name ?? deliverable.botId}
            delegated={delegated}
            active={activeId === deliverable.id}
            onOpen={onOpen}
          />
        );
      })}
      {hiddenCount > 0 ? (
        <button
          type="button"
          className="deliverables__more"
          onClick={() => setExpanded(true)}
        >
          +{hiddenCount} 个文件
        </button>
      ) : null}
      {expanded && deliverables.length > COLLAPSED_DELIVERABLE_COUNT ? (
        <button
          type="button"
          className="deliverables__more"
          onClick={() => setExpanded(false)}
        >
          收起
        </button>
      ) : null}
      {typeof overflow === 'number' && overflow > 0 ? (
        <span className="deliverables__overflow">另有 {overflow} 个文件未记录</span>
      ) : null}
    </section>
  );
}
