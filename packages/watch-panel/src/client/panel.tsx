/**
 * Analyses table shared by the workbench drawers.
 *
 * The old five-tab page is gone; this module keeps the read-only analyses list
 * (alert time, name, code, rule label, status) so a stock or rules drawer can
 * show "recent analyses" without leaving the page. Analysis text is always
 * plain text (`pre-wrap`), never HTML.
 */
import { Fragment } from 'react'
import type { CSSProperties, ReactElement } from 'react'
import type { WatchPanelKey } from './locales.ts'
import type { AnalysisDetail, AnalysisRecord, RuleConfig } from './viewModel.ts'
import {
  alertNameById,
  analysisBadge,
  describeSkipReason,
  formatClock,
  ruleLabel,
  shouldFetchAnalysis,
} from './viewModel.ts'

export interface AnalysesTableProps {
  t: (key: WatchPanelKey, params?: Record<string, unknown>) => string
  records: readonly AnalysisRecord[]
  alertNames: Record<string, string>
  alertTsById: ReadonlyMap<number, string | null>
  ruleById: ReadonlyMap<string, RuleConfig>
  details: Record<string, AnalysisDetail>
  errors: Record<string, boolean>
  expanded: number | null
  onToggle: (record: AnalysisRecord) => void
}

const detailRow: CSSProperties = { whiteSpace: 'normal' }

/**
 * The analyses table. A row opens the plain-text analysis when the record has
 * one; skipped rows never request a file (`shouldFetchAnalysis`).
 */
export function AnalysesTable(props: AnalysesTableProps): ReactElement {
  const { t, records, alertNames, alertTsById, ruleById, details, errors, expanded, onToggle } = props
  const names = alertNames ?? alertNameById(records.map((record) => ({ id: record.alert_id })))
  return (
    <div className="chives-scroll">
      <table className="chives-table">
        <thead>
          <tr>
            <th>{t('analysisTime')}</th>
            <th>{t('name')}</th>
            <th>{t('code')}</th>
            <th>{t('alertRule')}</th>
            <th>{t('reason')}</th>
            <th>{t('analysisStatus')}</th>
          </tr>
        </thead>
        <tbody>
          {records.map((record) => {
            const id = record.alert_id
            const status = analysisBadge(record)
            const reason = status === 'skipped' ? describeSkipReason(record.reason) : ''
            const detail = details[String(id)]
            const open = expanded === id
            return (
              <Fragment key={id}>
                <tr
                  className="is-clickable"
                  onClick={() => { if (shouldFetchAnalysis(record) || status === 'skipped') onToggle(record) }}
                >
                  <td>{formatClock(alertTsById.get(id) ?? record.started_at)}</td>
                  <td>{names[String(id)] ?? record.code ?? '\u2014'}</td>
                  <td>{record.code ?? '\u2014'}</td>
                  <td title={ruleLabel(record.rule_id, ruleById)}>{ruleLabel(record.rule_id, ruleById)}</td>
                  <td>{reason || '\u2014'}</td>
                  <td>
                    <span className={`chives-badge ${status === 'done' ? 'is-healthy' : status === 'failed' || status === 'timeout' ? 'is-critical' : 'is-idle'}`}>
                      {t(status === 'done' ? 'analysisDone' : status === 'failed' ? 'analysisFailed' : status === 'timeout' ? 'analysisTimeout' : status === 'skipped' ? 'analysisSkipped' : 'analysisUnknown')}
                    </span>
                  </td>
                </tr>
                {open ? (
                  <tr>
                    <td colSpan={5} style={detailRow}>
                      <div className="chives-detail">
                        {status === 'skipped' ? (
                          <div className="chives-empty">{reason ? t('analysisNoAnalysisReason', { reason }) : t('analysisNoAnalysis')}</div>
                        ) : errors[String(id)] ? (
                          <div className="chives-empty">{t('analysisUnavailable')}</div>
                        ) : detail ? (
                          <div className="chives-mono">{detail.markdown}</div>
                        ) : (
                          <div className="chives-empty">{t('analysisLoading')}</div>
                        )}
                        {detail?.truncated ? <div className="chives-empty">{t('analysisTruncated')}</div> : null}
                      </div>
                    </td>
                  </tr>
                ) : null}
              </Fragment>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
