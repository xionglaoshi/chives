import type { ReactElement } from 'react';

import type { MarketDashboardDto, MarketIndexDto } from '@chives/server/protocol';

import type { SectionState } from './ExpertSidebarData';
import {
  formatAmount,
  formatPercent,
  formatPrice,
  priceDirection
} from './ExpertSidebarFormat';
import { ExpertSidebarSparkline } from './ExpertSidebarSparkline';

export interface ExpertSidebarMarketProps {
  state: SectionState<MarketDashboardDto>;
  embedded?: boolean;
}

function MarketSkeleton(): ReactElement {
  return (
    <div className="expert-sidebar__skeleton" aria-hidden="true">
      {Array.from({ length: 5 }, (_, index) => (
        <span className="skeleton expert-sidebar__skeleton-row" key={index} />
      ))}
    </div>
  );
}

function IndexRow({ index }: { index: MarketIndexDto }): ReactElement {
  const direction = priceDirection(index.changePct);
  return (
    <li className="expert-sidebar__index">
      <span className="expert-sidebar__index-name">{index.name}</span>
      <span className="expert-sidebar__index-spark">
        <ExpertSidebarSparkline values={index.spark} label={index.name} />
      </span>
      <span className="expert-sidebar__index-price">{formatPrice(index.price)}</span>
      <span className={`expert-sidebar__index-change expert-sidebar__price--${direction}`}>
        {formatPercent(index.changePct)}
      </span>
    </li>
  );
}

export function ExpertSidebarMarket({ state, embedded = false }: ExpertSidebarMarketProps): ReactElement {
  if (state.status === 'loading' || state.data === null) {
    return (
      <section className={embedded ? "mb-market-overview" : "expert-sidebar__section"} aria-label="大盘">
        {!embedded && <h3 className="expert-sidebar__heading">大盘</h3>}
        {state.status === 'error' ? (
          <p className="expert-sidebar__error" role="status">
            暂时取不到，稍后自动重试
          </p>
        ) : (
          <MarketSkeleton />
        )}
      </section>
    );
  }

  const market = state.data;
  return (
    <section className={embedded ? "mb-market-overview" : "expert-sidebar__section"} aria-label="大盘">
      {!embedded && <h3 className="expert-sidebar__heading">大盘</h3>}
      {state.status === 'error' ? (
        <p className="expert-sidebar__error" role="status">
          暂时取不到，稍后自动重试
        </p>
      ) : null}
      <ul className="expert-sidebar__indexes">
        {market.indexes.map((index) => (
          <IndexRow index={index} key={index.code} />
        ))}
      </ul>
      <dl className="expert-sidebar__stats">
        <div className="expert-sidebar__stat">
          <dt>两市成交额</dt>
          <dd>{formatAmount(market.amountYuan)}</dd>
        </div>
        <div className="expert-sidebar__stat">
          <dt>上涨 / 下跌</dt>
          <dd>
            <span className="expert-sidebar__price--up">{market.breadth.up ?? '—'}</span>
            {' / '}
            <span className="expert-sidebar__price--down">{market.breadth.down ?? '—'}</span>
          </dd>
        </div>
        <div className="expert-sidebar__stat">
          <dt>涨停 / 跌停</dt>
          <dd>
            <span className="expert-sidebar__price--up">{market.limit.limitUp ?? '—'}</span>
            {' / '}
            <span className="expert-sidebar__price--down">{market.limit.limitDown ?? '—'}</span>
          </dd>
        </div>
      </dl>
      {market.stale && <p className="expert-sidebar__note">数据可能滞后</p>}
    </section>
  );
}
