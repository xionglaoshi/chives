import type { ReactElement } from 'react';

import type { MessageAttachmentDto } from '@chives/server/protocol';

import { Logo } from '../brand/Logo';
import { Composer } from './Composer';
import './Welcome.css';

export const STARTERS = [
  { title: '点评一份财报', description: '读原文，对比预告和一致预期，给出估值位置' },
  { title: '今天盘面怎么样', description: '指数、行业强弱、涨停梯队和资金流' },
  { title: '帮我找几只候选', description: '按估值、预期修正、资金和板块强度筛选' },
  { title: '每天早上给我发晨报', description: '隔夜外盘、公告和当天日历，开盘前送达' }
] as const;

interface WelcomeCopy {
  title: string;
  subtitle: string;
  starters: ReadonlyArray<{ title: string; description: string }>;
}

const EXPERT_COPY: WelcomeCopy = {
  title: '今天想研究什么？',
  subtitle: '总调度。啥事都可以找他',
  starters: STARTERS
};

/** Bots with their own first-run copy; others fall back to their name and role. */
const COPY_BY_BOT: Record<string, WelcomeCopy> = {
  operator: EXPERT_COPY
};

function welcomeCopy(botId: string | undefined, botName?: string, botRole?: string): WelcomeCopy {
  const known = botId === undefined ? undefined : COPY_BY_BOT[botId];
  if (known !== undefined) return known;
  if (botId === undefined || botName === undefined) return EXPERT_COPY;
  return { title: `想让${botName}做什么？`, subtitle: botRole ?? '', starters: [] };
}

const BOUNDARIES = [
  '只做 A 股研究，外盘作为参考',
  '不连接真实券商，下单只在模拟盘',
  '所有数据带来源和时间'
] as const;

export interface WelcomeProps {
  value: string;
  onChange: (value: string) => void;
  onSend: (text: string) => void;
  onStop: () => void;
  running: boolean;
  sending: boolean;
  notice: string | null;
  focusToken?: number;
  disabled?: boolean;
  disabledReason?: string;
  botId?: string;
  botName?: string;
  botRole?: string;
  placeholder?: string;
  attachments?: readonly MessageAttachmentDto[];
  onAddFiles?: (files: File[]) => void;
  onRemoveAttachment?: (path: string) => void;
  uploading?: boolean;
  uploadNotice?: string | null;
}

/** First-run state shown while the current bot's timeline is empty. */
export function Welcome({
  value,
  onChange,
  onSend,
  onStop,
  running,
  sending,
  notice,
  focusToken,
  disabled = false,
  disabledReason,
  botId,
  botName,
  botRole,
  placeholder = '例如：帮我看看宁德时代最新一期财报',
  attachments = [],
  onAddFiles,
  onRemoveAttachment,
  uploading = false,
  uploadNotice = null
}: WelcomeProps): ReactElement {
  const copy = welcomeCopy(botId, botName, botRole);
  return (
    <div className="welcome">
      <div className="welcome__inner">
        <div className="welcome__hero">
          <Logo size={44} />
          <h1 className="welcome__title">{copy.title}</h1>
          {copy.subtitle === '' ? null : <p className="welcome__subtitle">{copy.subtitle}</p>}
        </div>

        <Composer
          value={value}
          onChange={onChange}
          onSend={onSend}
          onStop={onStop}
          running={running}
          sending={sending}
          notice={notice}
          placeholder={placeholder}
          showHint={false}
          autoFocus
          {...(focusToken === undefined ? {} : { focusToken })}
          disabled={disabled}
          {...(disabledReason === undefined ? {} : { disabledReason })}
          {...(botId === undefined ? {} : { botId })}
          attachments={attachments}
          {...(onAddFiles === undefined ? {} : { onAddFiles })}
          {...(onRemoveAttachment === undefined ? {} : { onRemoveAttachment })}
          uploading={uploading}
          uploadNotice={uploadNotice}
        />

        {copy.starters.length === 0 ? null : (
        <div className="welcome__starters">
          {copy.starters.map((starter) => (
            <button
              key={starter.title}
              type="button"
              className="welcome__starter"
              onClick={() => onSend(starter.title)}
              disabled={disabled}
            >
              <span className="welcome__starter-title">{starter.title}</span>
              <span className="welcome__starter-description">{starter.description}</span>
            </button>
          ))}
        </div>
        )}

        <div className="welcome__boundaries">
          {BOUNDARIES.map((boundary) => (
            <span key={boundary}>{boundary}</span>
          ))}
        </div>
      </div>
    </div>
  );
}
