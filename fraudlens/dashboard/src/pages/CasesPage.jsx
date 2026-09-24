import { useDeferredValue, useMemo } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import RiskGauge from '../components/RiskGauge.jsx'
import ResourceState from '../components/ResourceState.jsx'
import { useFraudLensData } from '../data/FraudLensData.jsx'
import { getRiskBand, getStatusLabel, getVerdictLabel } from '../lib/case.js'
import { formatCurrency, formatNumber, formatPercent, pluralize, titleCaseToken } from '../lib/format.js'

const RISK_OPTIONS = [
  ['critical', 'Critical (85%+)'],
  ['high', 'High (60–84.99%)'],
  ['elevated', 'Elevated (30–59.99%)'],
  ['low', 'Lower (<30%)'],
]

function StatCard({ label, value, detail, tone = '' }) {
  return (
    <article className={`stat-card ${tone}`}>
      <span className="stat-label">{label}</span>
      <strong>{value}</strong>
      <span className="stat-detail">{detail}</span>
    </article>
  )
}

function CaseCard({ caseRecord }) {
  const risk = getRiskBand(caseRecord.fraud_probability)
  const affected = Number(caseRecord.affected_count) || 0

  return (
    <Link
      to={`/cases/${encodeURIComponent(caseRecord.case_id)}`}
      className={`case-card risk-${risk.key}`}
      aria-label={`Open ${caseRecord.case_id}, ${getVerdictLabel(caseRecord.verdict)}, ${risk.label} risk`}
    >
      <div className="case-card-top">
        <strong className="case-id" translate="no">{caseRecord.case_id}</strong>
        <span className={`verdict ${caseRecord.verdict || 'uncertain'}`}>
          {getVerdictLabel(caseRecord.verdict)}
        </span>
      </div>

      <div className="case-card-main">
        <RiskGauge value={caseRecord.fraud_probability} size={68} />
        <div className="case-card-copy">
          <span className="stat-label">Fraud likelihood</span>
          <strong>{titleCaseToken(caseRecord.pattern || 'Pattern not supplied')}</strong>
          <span>{formatPercent(caseRecord.fraud_probability)} · {risk.label} risk · {getStatusLabel(caseRecord.status)}</span>
        </div>
      </div>

      <div className="case-card-meter" aria-hidden="true">
        <i style={{ width: `${Math.max(0, Math.min(100, Number(caseRecord.fraud_probability) * 100 || 0))}%` }} />
      </div>

      <div className="case-card-footer">
        <div>
          <span>Exposure</span>
          <strong>{formatCurrency(caseRecord.exposure_usd)}</strong>
        </div>
        <div>
          <span>Episode</span>
          <strong>{pluralize(affected, 'transaction')}</strong>
        </div>
        {caseRecord.sar ? <span className="sar-chip">SAR Draft</span> : <span className="neutral-chip">No SAR draft</span>}
      </div>
    </Link>
  )
}

function QueueSkeleton() {
  return (
    <div className="case-grid" aria-hidden="true">
      {Array.from({ length: 6 }, (_, index) => (
        <div className="case-card skeleton-card" key={index}>
          <span className="skeleton-line short" />
          <span className="skeleton-block" />
          <span className="skeleton-line" />
          <span className="skeleton-line medium" />
        </div>
      ))}
    </div>
  )
}

export default function CasesPage() {
  const { casesResource, statsResource } = useFraudLensData()
  const [searchParams, setSearchParams] = useSearchParams()
  const query = searchParams.get('q') || ''
  const verdict = searchParams.get('verdict') || 'all'
  const risk = searchParams.get('risk') || 'all'
  const sarOnly = searchParams.get('sar') === 'true'
  const sort = searchParams.get('sort') || 'risk'
  const deferredQuery = useDeferredValue(query.trim().toLowerCase())

  function updateFilter(name, value, defaultValue) {
    const next = new URLSearchParams(searchParams)
    if (!value || value === defaultValue) next.delete(name)
    else next.set(name, value)
    setSearchParams(next, { replace: true })
  }

  function resetFilters() {
    setSearchParams({}, { replace: true })
  }

  const cases = Array.isArray(casesResource.data) ? casesResource.data : []
  const filteredCases = useMemo(() => {
    const matching = cases.filter(item => {
      const matchesQuery = !deferredQuery || [
        item.case_id,
        item.pattern,
        item.verdict,
        item.status,
      ].some(value => String(value || '').toLowerCase().includes(deferredQuery))
      const matchesVerdict = verdict === 'all' || item.verdict === verdict
      const matchesRisk = risk === 'all' || getRiskBand(item.fraud_probability).key === risk
      const matchesSar = !sarOnly || Boolean(item.sar)
      return matchesQuery && matchesVerdict && matchesRisk && matchesSar
    })

    return matching.sort((left, right) => {
      if (sort === 'exposure') {
        return (Number(right.exposure_usd) || 0) - (Number(left.exposure_usd) || 0)
      }
      if (sort === 'case') return String(left.case_id).localeCompare(String(right.case_id))
      return (Number(right.fraud_probability) || 0) - (Number(left.fraud_probability) || 0)
    })
  }, [cases, deferredQuery, risk, sarOnly, sort, verdict])

  if (casesResource.status === 'loading') {
    return (
      <main id="main-content" className="home" tabIndex="-1">
        <header className="page-header">
          <div>
            <p className="eyebrow">Analyst Workspace</p>
            <h1>Case-Pack Review</h1>
            <p className="page-lede">
              Triage recorded HHGOA investigations with model likelihood, supporting claims, and
              human approval boundaries kept distinct.
            </p>
          </div>
          <span className="loading-chip" role="status">Loading case records…</span>
        </header>
        <ResourceState
          status="loading"
          title="Loading the investigation queue…"
          message="Case summaries will appear here when the API responds."
        />
        <QueueSkeleton />
      </main>
    )
  }

  if (casesResource.status === 'error') {
    return (
      <main id="main-content" className="home" tabIndex="-1">
        <header className="page-header">
          <div>
            <p className="eyebrow">Analyst Workspace</p>
            <h1>Case-Pack Review</h1>
            <p className="page-lede">The queue could not be loaded from the dashboard API.</p>
          </div>
        </header>
        <ResourceState
          status="error"
          title="Investigation queue unavailable"
          message={`${casesResource.error} Confirm the API is running, then retry.`}
          actionLabel="Retry Case Queue"
          onAction={casesResource.retry}
        />
      </main>
    )
  }

  if (cases.length === 0) {
    return (
      <main id="main-content" className="home" tabIndex="-1">
        <header className="page-header">
          <div>
            <p className="eyebrow">Analyst Workspace</p>
            <h1>Case-Pack Review</h1>
            <p className="page-lede">The API responded, but no case-pack records are available.</p>
          </div>
        </header>
        <ResourceState
          status="empty"
          title="No investigations in the queue"
          message="Generate or restore case response files, then retry the API."
          actionLabel="Retry Case Queue"
          onAction={casesResource.retry}
        />
      </main>
    )
  }

  const fraudCount = cases.filter(item => item.verdict === 'fraud').length
  const sarDraftCount = cases.filter(item => item.sar).length
  const totalExposure = cases
    .filter(item => item.verdict === 'fraud')
    .reduce((sum, item) => sum + (Number(item.exposure_usd) || 0), 0)
  const transactionCount = Number(statsResource.data?.counts?.Transaction)
  const featuredCase = cases.find(item => item.case_id === 'HHG-014')

  return (
    <main id="main-content" className="home" tabIndex="-1">
      <header className="page-header">
        <div>
          <p className="eyebrow">Analyst Workspace</p>
          <h1>Case-Pack Review</h1>
          <p className="page-lede">
            Triage recorded investigations with model likelihood, supporting claims, and approval
            boundaries kept distinct. Scores are decision support—not proof or execution status.
          </p>
        </div>
        <div className="header-context">
          <span className="context-chip">{pluralize(cases.length, 'case')} returned</span>
          {featuredCase && (
            <Link className="featured-case" to={`/cases/${encodeURIComponent(featuredCase.case_id)}`}>
              <span>Focused graph example</span>
              <strong translate="no">HHG-014</strong>
            </Link>
          )}
        </div>
      </header>

      <section className="stat-cards overview-stats" aria-label="Case-pack summary">
        <StatCard
          label="Fraud Verdicts"
          value={formatNumber(fraudCount)}
          detail={`${formatPercent(cases.length ? fraudCount / cases.length : 0)} of returned cases`}
          tone="danger"
        />
        <StatCard
          label="SAR Drafts Available"
          value={formatNumber(sarDraftCount)}
          detail="Draft artifacts; filing is not confirmed"
        />
        <StatCard
          label="Fraud-Case Exposure"
          value={formatCurrency(totalExposure, { compact: true })}
          detail="Sum of fraud-verdict episode exposure"
        />
        <StatCard
          label="Graph Transactions"
          value={statsResource.status === 'success' && Number.isFinite(transactionCount)
            ? formatNumber(transactionCount, { compact: true })
            : '—'}
          detail={statsResource.status === 'loading'
            ? 'Reading graph snapshot…'
            : statsResource.status === 'error'
              ? 'Snapshot unavailable'
              : Number.isFinite(transactionCount)
                ? `Returned by ${statsResource.data?.graph || 'graph API'}`
                : 'Transaction count not supplied'}
          tone="neutral"
        />
        {statsResource.status === 'error' && (
          <button className="button secondary stat-retry" type="button" onClick={statsResource.retry}>
            Retry Graph Snapshot
          </button>
        )}
      </section>

      <section className="queue-section" aria-labelledby="queue-title">
        <div className="section-heading queue-title-row">
          <div>
            <p className="eyebrow">Triage Queue</p>
            <h2 id="queue-title">Recorded Investigations</h2>
          </div>
          <p className="queue-result-count" role="status" aria-live="polite">
            Showing {formatNumber(filteredCases.length)} of {formatNumber(cases.length)} cases
          </p>
        </div>

        <form className="filter-panel" role="search" aria-label="Filter case queue" onSubmit={event => event.preventDefault()}>
          <div className="search-field">
            <label htmlFor="case-search">Search cases</label>
            <input
              id="case-search"
              name="case-search"
              type="search"
              value={query}
              onChange={event => updateFilter('q', event.target.value, '')}
              placeholder="Case ID, pattern, or status…"
              autoComplete="off"
              spellCheck="false"
            />
          </div>
          <div className="filter-field">
            <label htmlFor="verdict-filter">Verdict</label>
            <select
              id="verdict-filter"
              name="verdict"
              value={verdict}
              onChange={event => updateFilter('verdict', event.target.value, 'all')}
            >
              <option value="all">All verdicts</option>
              <option value="fraud">Fraud</option>
              <option value="legitimate">Legitimate</option>
              <option value="uncertain">Uncertain</option>
            </select>
          </div>
          <div className="filter-field">
            <label htmlFor="risk-filter">Risk band</label>
            <select
              id="risk-filter"
              name="risk"
              value={risk}
              onChange={event => updateFilter('risk', event.target.value, 'all')}
            >
              <option value="all">All risk bands</option>
              {RISK_OPTIONS.map(([value, label]) => <option value={value} key={value}>{label}</option>)}
            </select>
          </div>
          <div className="filter-field">
            <label htmlFor="sort-filter">Sort</label>
            <select
              id="sort-filter"
              name="sort"
              value={sort}
              onChange={event => updateFilter('sort', event.target.value, 'risk')}
            >
              <option value="risk">High likelihood first</option>
              <option value="exposure">High exposure first</option>
              <option value="case">Case ID</option>
            </select>
          </div>
          <label className="check-field" htmlFor="sar-filter">
            <input
              id="sar-filter"
              name="sar"
              type="checkbox"
              checked={sarOnly}
              onChange={event => updateFilter('sar', event.target.checked ? 'true' : '', 'false')}
            />
            <span>SAR drafts only</span>
          </label>
          <button className="button secondary reset-filters" type="button" onClick={resetFilters}>
            Reset Filters
          </button>
        </form>

        {filteredCases.length === 0 ? (
          <ResourceState
            status="empty"
            title="No cases match these filters"
            message="Broaden the search or clear the queue filters to return to the full case pack."
            actionLabel="Reset Filters"
            onAction={resetFilters}
          />
        ) : (
          <div className="case-grid">
            {filteredCases.map(caseRecord => <CaseCard caseRecord={caseRecord} key={caseRecord.case_id} />)}
          </div>
        )}
      </section>
    </main>
  )
}
