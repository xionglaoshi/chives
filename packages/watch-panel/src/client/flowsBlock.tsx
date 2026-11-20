/**
 * Fund-flow block (T100): three columns — sector inflow, sector outflow, stock
 * inflow — plus the folded stock outflow column. Rows open the matching drawer.
 */
import type { ReactElement } from 'react'
import { DASH, formatStamp, isSectorCode } from './market.ts'
import {
  FLOW_COLUMNS,
  flowAmount,
  flowChange,
  flowColumns,
  flowGlyph,
  flowRows,
  flowSide,
  flowsProblem,
  northboundText,
  type FlowKind,
  type FlowsPayload,
  type NorthboundPayload,
} from './flows.ts'
import type { WatchPanelKey } from './locales.ts'

type Translate = (key: WatchPanelKey, params?: Record<string, unknown>) => string

export interface FlowsBlockProps {
  t: Translate
  flows: Partial<Record<FlowKind, FlowsPayload>>
  northbound: NorthboundPayload | null
  failed: boolean
  more: boolean
  onMore: (more: boolean) => void
  onSector: (code: string) => void
  onStock: (code: string) => void
}

function FlowColumn({ t, kind, payload, failed, onSector, onStock }: {
  t: Translate
  kind: FlowKind
  payload: FlowsPayload | undefined
  failed: boolean
  onSector: (code: string) => void
  onStock: (code: string) => void
}): ReactElement {
  const rows = flowRows(payload)
  const problem = flowsProblem(payload, failed)
  const stock = kind === 'stock_in' || kind === 'stock_out'
  return (
    <div className="chives-flow-col" data-flow={kind}>
      <div className="chives-flow-head">
        <span>{t(kind === 'sector_in' ? 'wbFlowSectorIn' : kind === 'sector_out' ? 'wbFlowSectorOut' : kind === 'stock_in' ? 'wbFlowStockIn' : 'wbFlowStockOut')}</span>
        <span className="chives-wb-meta">{rows.length || ''}</span>
      </div>
      {rows.length === 0 ? (
        <div className="chives-wb-empty">{problem ?? t('noData')}</div>
      ) : (
        <ol className="chives-flow-rows">
          {rows.map((row, position) => {
            const side = flowSide(row.mainNetYuan)
            const sector = !stock && isSectorCode(row.code)
            const clickable = stock ? row.code !== '' : sector
            return (
              <li key={`${kind}:${row.code}`}>
                <button
                  type="button"
                  className={`chives-flow-row${payload?.stale ? ' is-stale' : ''}`}
                  data-consumer={stock ? 'stock' : 'sector'}
                  disabled={!clickable}
                  onClick={() => { if (stock) onStock(row.code); else if (sector) onSector(row.code) }}
                >
                  <span className="chives-flow-rank">{row.rank ?? position + 1}</span>
                  <span className="chives-flow-name">{row.name}<span className="chives-code">{row.code}</span></span>
                  <span className={`chives-flow-net chives-num is-${side}`}>{flowGlyph(row.mainNetYuan)} {flowAmount(row.mainNetYuan)}</span>
                  <span className={`chives-flow-change chives-num is-${row.changePct === null ? 'flat' : row.changePct > 0 ? 'up' : row.changePct < 0 ? 'down' : 'flat'}`}>{flowChange(row.changePct)}</span>
                </button>
              </li>
            )
          })}
        </ol>
      )}
    </div>
  )
}

/** Header carries the vendor definition, the data time and northbound when available. */
export function FlowsBlock({ t, flows, northbound, failed, more, onMore, onSector, onStock }: FlowsBlockProps): ReactElement {
  const columns = flowColumns(more)
  const asOf = columns.map((kind) => flows[kind]?.asOf ?? null).find((value) => value !== null) ?? null
  const definition = flows[FLOW_COLUMNS[0]!]?.definition ?? t('wbFlowDefinition')
  const north = northboundText(northbound)
  const stale = columns.map((kind) => flows[kind]).find((payload) => payload?.stale) ?? null
  const staleNote = stale === null ? null : (stale.reason ?? t('stale'))
  return (
    <section className="chives-wb-section chives-wb-flows" data-wb="flows" aria-label={t('wbFlows')}>
      <div className="chives-wb-section-head">
        <span className="chives-wb-label">{t('wbFlows')}</span>
        <span className="chives-wb-meta">{t('asOf')} {asOf === null ? DASH : formatStamp(asOf)}</span>
        {staleNote ? <span className="chives-wb-meta is-stale">{staleNote}</span> : null}
        {north ? <span className="chives-flow-north">{north}</span> : null}
        <button type="button" className="chives-wb-more" aria-expanded={more} onClick={() => onMore(!more)}>
          {more ? t('wbFlowsLess') : t('wbFlowsMore')}
        </button>
      </div>
      <div className="chives-flow-headline">
        <span className="chives-flow-def">{definition}</span>
      </div>
      {failed ? <div className="chives-wb-banner is-warn">{t('wbFlowsUnavailable')}</div> : null}
      <div className={`chives-flow-grid${more ? ' has-more' : ''}`}>
        {columns.map((kind) => (
          <FlowColumn key={kind} t={t} kind={kind} payload={flows[kind]} failed={failed} onSector={onSector} onStock={onStock} />
        ))}
      </div>
    </section>
  )
}
