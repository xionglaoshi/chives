import type { ReactElement } from 'react';

import type { BotSummary } from '@chives/server/protocol';

import { BotAvatar } from '../brand/BotAvatar';
import { mcpNames, shortenWorkspacePath, skillSummary } from '../utils/botProfile';
import { BOT_STATUS_TONES, botStatusLabel } from '../utils/bots';
import './BotsOverview.css';

function memorySummary(bot: BotSummary): string {
  const count = bot.memoryCount ?? 0;
  if (count === 0) return '还没有记忆';
  const updatedAt = bot.memoryUpdatedAt;
  return updatedAt === undefined || updatedAt === null || updatedAt === ''
    ? `${count} 条`
    : `${count} 条 · 最近更新 ${updatedAt.slice(0, 10)}`;
}

export interface BotsOverviewProps {
  bots: BotSummary[];
  loading: boolean;
  error: string | null;
  onRetry: () => void;
  onOpenConversation: (botId: string) => void;
  onOpenProfile: (botId: string) => void;
}

export function BotsOverview({
  bots,
  loading,
  error,
  onRetry,
  onOpenConversation,
  onOpenProfile
}: BotsOverviewProps): ReactElement {
  const working = bots.filter(
    (bot) => bot.status === 'working' || bot.status === 'starting'
  ).length;
  const pending = bots.reduce((total, bot) => total + bot.pendingApprovals, 0);
  const names = new Map(bots.map((bot) => [bot.id, bot.name]));

  return (
    <div className="bots-overview">
      <header className="bots-overview__header">
        <div className="bots-overview__intro">
          <h1 className="bots-overview__title">人才市场</h1>
          <p className="bots-overview__subtitle">
            查看 Bot 的分工、技能与资料，选择合适的 Bot 继续对话。
          </p>
        </div>
        <div className="bots-overview__stats" aria-label="Bot 概览统计">
          <span>
            <strong>{bots.length}</strong> 个 Bot
          </span>
          <span>
            <strong className="bots-overview__stat--gold">{working}</strong> 个工作中
          </span>
          <span>
            <strong className="bots-overview__stat--gold">{pending}</strong> 项待批准
          </span>
        </div>
      </header>

      {!loading && bots.length > 0 && working === 0 && pending === 0 ? (
        <p className="bots-overview__quiet" role="status">
          现在没有 Bot 在运行。需要时从下面进入对话。
        </p>
      ) : null}

      {loading && bots.length === 0 ? (
        <div className="bots-overview__skeleton" role="status" aria-label="Bot 列表加载中">
          {Array.from({ length: 4 }, (_, index) => (
            <span className="skeleton bots-overview__skeleton-card" key={index} />
          ))}
        </div>
      ) : null}

      {!loading && bots.length === 0 ? (
        <div className="bots-overview__empty" role="status">
          {error === null ? '还没有可用的 Bot。' : `Bot 列表没有加载出来：${error}`}
          {error === null ? null : (
            <button type="button" className="bots-overview__retry" onClick={onRetry}>
              重试
            </button>
          )}
        </div>
      ) : null}

      <div className="bots-overview__grid">
        {bots.map((bot) => {
          const delegates = bot.canDelegateTo.map((id) => names.get(id) ?? id);
          const tools = mcpNames(bot.mcp);
          const statusLabel = botStatusLabel(bot);
          return (
            <article
              className={`bots-overview__card${
                bot.background ? ' bots-overview__card--background' : ''
              }`}
              key={bot.id}
              aria-label={`${bot.name} 资料卡`}
            >
              <div className="bots-overview__card-head">
                <BotAvatar
                  emblem={bot.avatar.emblem}
                  tone={bot.avatar.tone}
                  size={18}
                  name={bot.name}
                />
                <div className="bots-overview__identity">
                  <h2 className="bots-overview__name">{bot.name}</h2>
                  <div className="bots-overview__role">{bot.role}</div>
                </div>
                <span
                  className={`bots-overview__status bots-overview__status--${
                    BOT_STATUS_TONES[bot.status]
                  }`}
                >
                  {statusLabel}
                </span>
              </div>

              <dl className="bots-overview__facts">
                <dt>技能</dt>
                <dd>{skillSummary(bot.skills)}</dd>
                <dt>数据与工具</dt>
                <dd>{tools.length === 0 ? '暂无' : tools.join('、')}</dd>
                <dt>可以委派</dt>
                <dd>{delegates.length === 0 ? '无' : delegates.join('、')}</dd>
                <dt>主动任务</dt>
                <dd>
                  {bot.proactiveCount === undefined || bot.proactiveCount === 0
                    ? '暂无'
                    : `${bot.proactiveCount} 个已启用`}
                </dd>
                <dt>盯盘</dt>
                <dd>
                  {bot.watchCount === undefined || bot.watchCount === 0
                    ? '暂无'
                    : `${bot.watchCount} 条活跃`}
                </dd>
                <dt>记忆</dt>
                <dd>{memorySummary(bot)}</dd>
                <dt>工作目录</dt>
                <dd className="bots-overview__path" title={bot.workspacePath ?? ''}>
                  {bot.workspacePath === undefined || bot.workspacePath === ''
                    ? '—'
                    : shortenWorkspacePath(bot.workspacePath)}
                </dd>
                <dt>模型</dt>
                <dd>{bot.modelDisplayName ?? bot.model}</dd>
              </dl>

              <div className="bots-overview__actions">
                <button
                  type="button"
                  className="bots-overview__action bots-overview__action--primary"
                  onClick={() => onOpenConversation(bot.id)}
                >
                  对话
                </button>
                <button
                  type="button"
                  className="bots-overview__action"
                  onClick={() => onOpenProfile(bot.id)}
                >
                  查看资料
                </button>
              </div>
            </article>
          );
        })}
      </div>
    </div>
  );
}
