import type { ReactElement } from 'react';

import type { PortfolioDashboardDto } from '@chives/server/protocol';

import type { SectionState } from './ExpertSidebarData';
import {
  formatPercent,
  formatPrice,
  HIDDEN,
  priceDirection
} from './ExpertSidebarFormat';

export interface ExpertSidebarPortfolioProps {
  state: SectionState<PortfolioDashboardDto>;
  hidden: boolean;
  onPickName: (name: string) => void;
}

function formatMoney(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return '—';
  const sign = value > 0 ? '+' : value < 0 ? '-' : '';
  return `${sign}${Math.abs(value).toLocaleString('zh-CN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  })}`;
}

function PortfolioSkeleton(): ReactElement {
  return (
    <div className="expert-sidebar__skeleton" aria-hidden="true">
      {Array.from({ length: 3 }, (_, index) => (
        <span className="skeleton expert-sidebar__skeleton-row" key={index} />
      ))}
    </div>
  );
}

export function ExpertSidebarPortfolio({
  state,
  hidden,
  onPickName
}: ExpertSidebarPortfolioProps): ReactElement {
  const body =
    state.status === 'error' && state.data === null ? (
      <p className="expert-sidebar__error" role="status">
        暂时取不到，稍后自动重试
      </p>
    ) : state.status === 'loading' || state.data === null ? (
      <PortfolioSkeleton />
    ) : (
      <PortfolioBody data={state.data} hidden={hidden} onPickName={onPickName} />
    );

  return (
    <section className="expert-sidebar__section" aria-label="我的持仓">
      <h3 className="expert-sidebar__heading">我的持仓</h3>
      {state.status === 'error' && state.data !== null ? (
        <p className="expert-sidebar__error" role="status">
          暂时取不到，稍后自动重试
        </p>
      ) : null}
      {body}
    </section>
  );
}

function PortfolioBody({
  data,
  hidden,
  onPickName
}: {
  data: PortfolioDashboardDto;
  hidden: boolean;
  onPickName: (name: string) => void;
}): ReactElement {
  const pnlDirection = priceDirection(data.summary.totalPnl);
  const todayText =
    data.summary.todayPnl === null ? '—' : formatMoney(data.summary.todayPnl);
  return (
    <>
      <dl className="expert-sidebar__stats expert-sidebar__stats--portfolio">
        <div className="expert-sidebar__stat">
          <dt>总市值</dt>
          <dd>{hidden ? HIDDEN : formatMoney(data.summary.totalMarketValue)}</dd>
        </div>
        <div className="expert-sidebar__stat">
          <dt>总浮盈</dt>
          <dd className={`expert-sidebar__price--${pnlDirection}`}>
            {hidden ? HIDDEN : formatMoney(data.summary.totalPnl)}
            <span className="expert-sidebar__pct">{formatPercent(data.summary.totalPnlPct)}</span>
          </dd>
        </div>
        <div className="expert-sidebar__stat">
          <dt>今日盈亏</dt>
          <dd>{hidden && data.summary.todayPnl !== null ? HIDDEN : todayText}</dd>
        </div>
        <div className="expert-sidebar__stat">
          <dt>现金</dt>
          <dd>
            {data.cash === null ? '未设置' : hidden ? HIDDEN : formatMoney(data.cash)}
          </dd>
        </div>
      </dl>

      {data.empty ? (
        <p className="expert-sidebar__empty">
          还没有记录持仓。直接在对话里说，如&apos;我 7.9 元买了 400 股柳工&apos;。
        </p>
      ) : null}
      <ul className="expert-sidebar__positions">
        {data.positions.map((row) => {
          const pnl = priceDirection(row.pnlPct);
          const change = priceDirection(row.changePct);
          return (
            <li key={row.code} className="expert-sidebar__position">
              <button
                type="button"
                className="expert-sidebar__position-button"
                onClick={() => onPickName(row.name)}
                aria-label={`看看${row.name}`}
                title={row.priceAvailable ? undefined : '行情缺失或停牌'}
              >
                <span className="expert-sidebar__position-line">
                  <span className="expert-sidebar__position-name">{row.name}</span>
                  <span className={`expert-sidebar__pct expert-sidebar__price--${pnl}`}>
                    {formatPercent(row.pnlPct)}
                  </span>
                </span>
                <span className="expert-sidebar__position-line expert-sidebar__position-meta">
                  <span>
                    {hidden ? HIDDEN : (row.qty ?? '—')} 股 · 成本{' '}
                    {hidden ? HIDDEN : formatPrice(row.costPrice)}
                  </span>
                  <span className={`expert-sidebar__price--${change}`}>
                    {formatPercent(row.changePct)}
                  </span>
                </span>
                <span className="expert-sidebar__position-line expert-sidebar__position-meta">
                  <span className="expert-sidebar__position-code">{row.code}</span>
                  <span>现价 {formatPrice(row.price)}</span>
                </span>
              </button>
            </li>
          );
        })}
      </ul>
      {data.unpriced.length > 0 ? (
        <p className="expert-sidebar__note">
          {data.unpriced.map((row) => row.name || row.code).join('、')} 取不到价格，未计入汇总
        </p>
      ) : null}
    </>
  );
}
