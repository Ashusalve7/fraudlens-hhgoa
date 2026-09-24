import { useEffect, useMemo } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import ResourceState from './ResourceState.jsx'
import { useFraudLensData } from '../data/FraudLensData.jsx'
import { getVerdictLabel } from '../lib/case.js'
import { formatCurrency, formatLatency, formatNumber, pluralize, titleCaseToken } from '../lib/format.js'

const COLORS = {
  fraud: '#b42318',
  legitimate: '#087443',
  uncertain: '#9a6700',
}

function StatCard({ label, value, detail }) {
  return (
    <article className="stat-card">
      <span className="stat-label">{label}</span>
      <strong>{value}</strong>
      <span className="stat-detail">{detail}</span>
    </article>
  )
}

export default function AnalyticsView() {
  const { casesResource } = useFraudLensData()

  useEffect(() => {
    document.getElementById('main-content')?.focus()
  }, [])

  const cases = Array.isArray(casesResource.data) ? casesResource.data : []
  const analytics = useMemo(() => {
    const fraudCases = cases.filter(item => item.verdict === 'fraud')
    const byVerdict = ['fraud', 'legitimate', 'uncertain']
      .map(verdict => ({
        name: verdict,
        label: getVerdictLabel(verdict),
        value: cases.filter(item => item.verdict === verdict).length,
      }))
      .filter(item => item.value > 0)
    const patternCounts = fraudCases.reduce((counts, item) => {
      const key = item.pattern || 'pattern_not_supplied'
      counts[key] = (counts[key] || 0) + 1
      return counts
    }, {})
    const byPattern = Object.entries(patternCounts)
      .map(([name, value]) => ({ name: titleCaseToken(name), value }))
      .sort((left, right) => right.value - left.value)
    const buckets = [
      ['0–19.99', 0, 20],
      ['20–39.99', 20, 40],
      ['40–59.99', 40, 60],
      ['60–79.99', 60, 80],
      ['80–100', 80, 100],
    ].map(([range, lower, upper]) => ({
      range,
      cases: cases.filter(item => {
        const probability = Number(item.fraud_probability) * 100
        return probability >= lower && (range === '80–100' ? probability <= 100 : probability < upper)
      }).length,
    }))
    const totalExposure = fraudCases.reduce(
      (sum, item) => sum + (Number(item.exposure_usd) || 0),
      0,
    )
    const totalAffectedTransactions = cases.reduce(
      (sum, item) => sum + Math.max(0, Number(item.affected_count) || 0),
      0,
    )
    const totalLatency = cases.reduce((sum, item) => sum + (Number(item.latency_s) || 0), 0)
    const biggest = [...fraudCases].sort(
      (left, right) => (Number(right.exposure_usd) || 0) - (Number(left.exposure_usd) || 0),
    )[0]

    return {
      fraudCases,
      byVerdict,
      byPattern,
      buckets,
      totalExposure,
      totalAffectedTransactions,
      averageLatency: cases.length ? totalLatency / cases.length : 0,
      biggest,
      sarDraftCount: cases.filter(item => item.sar).length,
    }
  }, [cases])

  if (casesResource.status === 'loading') {
    return (
      <main id="main-content" className="analytics-page" tabIndex={-1}>
        <header className="page-header">
          <div>
            <p className="eyebrow">Descriptive Snapshot</p>
            <h1>Case-Pack Analytics</h1>
          </div>
        </header>
        <ResourceState
          status="loading"
          title="Loading case-pack analytics…"
          message="Chart code and case metrics are loading for this route."
        />
      </main>
    )
  }

  if (casesResource.status === 'error') {
    return (
      <main id="main-content" className="analytics-page" tabIndex={-1}>
        <header className="page-header">
          <div>
            <p className="eyebrow">Descriptive Snapshot</p>
            <h1>Case-Pack Analytics</h1>
          </div>
        </header>
        <ResourceState
          status="error"
          title="Analytics source unavailable"
          message={`${casesResource.error} Retry the case queue before drawing conclusions.`}
          actionLabel="Retry Case Queue"
          onAction={casesResource.retry}
        />
      </main>
    )
  }

  if (cases.length === 0) {
    return (
      <main id="main-content" className="analytics-page" tabIndex={-1}>
        <header className="page-header">
          <div>
            <p className="eyebrow">Descriptive Snapshot</p>
            <h1>Case-Pack Analytics</h1>
          </div>
        </header>
        <ResourceState
          status="empty"
          title="No case records to analyze"
          message="The API returned an empty queue. Restore the case pack and retry."
          actionLabel="Retry Case Queue"
          onAction={casesResource.retry}
        />
      </main>
    )
  }

  return (
    <main id="main-content" className="analytics-page" tabIndex={-1}>
      <header className="page-header">
        <div>
          <p className="eyebrow">Descriptive Snapshot</p>
          <h1>Case-Pack Analytics</h1>
          <p className="page-lede">
            Distribution and recorded-run summaries for the returned case pack. This is not a live
            monitoring view, model-validation report, or estimate of production performance.
          </p>
        </div>
        <span className="context-chip">{pluralize(cases.length, 'case')} included</span>
      </header>

      <section className="stat-cards analytics-stats" aria-label="Case-pack analytics summary">
        <StatCard
          label="Fraud Verdicts"
          value={formatNumber(analytics.fraudCases.length)}
          detail={`${formatNumber(cases.length - analytics.fraudCases.length)} non-fraud verdicts`}
        />
        <StatCard
          label="Fraud-Case Exposure"
          value={formatCurrency(analytics.totalExposure, { compact: true })}
          detail="Episode exposure sum"
        />
        <StatCard
          label="SAR Drafts"
          value={formatNumber(analytics.sarDraftCount)}
          detail="Draft availability; filing unconfirmed"
        />
        <StatCard
          label="Affected Transactions"
          value={formatNumber(analytics.totalAffectedTransactions)}
          detail="Transactions in recorded case episodes"
        />
        <StatCard
          label="Average Recorded Run"
          value={formatLatency(analytics.averageLatency)}
          detail="Mean wall-clock value in case files"
        />
        <StatCard
          label="Largest Exposure"
          value={analytics.biggest ? formatCurrency(analytics.biggest.exposure_usd, { compact: true }) : '—'}
          detail={analytics.biggest?.case_id || 'No fraud case returned'}
        />
      </section>

      <section className="analytics-section" aria-labelledby="distribution-title">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Case Distribution</p>
            <h2 id="distribution-title">Verdicts &amp; Probability</h2>
          </div>
          <span className="neutral-chip">Counts, not rates</span>
        </div>

        <div className="chart-row">
          <article className="panel chart-panel">
            <h3>Verdict Mix</h3>
            <div
              className="chart-frame"
              role="img"
              aria-label={`Verdict mix: ${analytics.byVerdict.map(item => `${item.label} ${item.value}`).join(', ')}`}
            >
              <ResponsiveContainer width="100%" height={230}>
                <PieChart>
                  <Pie
                    data={analytics.byVerdict}
                    dataKey="value"
                    nameKey="label"
                    innerRadius={58}
                    outerRadius={88}
                    paddingAngle={2}
                    isAnimationActive={false}
                  >
                    {analytics.byVerdict.map(item => <Cell key={item.name} fill={COLORS[item.name]} />)}
                  </Pie>
                  <Tooltip />
                </PieChart>
              </ResponsiveContainer>
            </div>
          </article>

          <article className="panel chart-panel">
            <h3>Estimated Fraud-Likelihood Bands</h3>
            <div
              className="chart-frame"
              role="img"
              aria-label={`Probability distribution: ${analytics.buckets.map(item => `${item.range} percent ${item.cases} cases`).join(', ')}`}
            >
              <ResponsiveContainer width="100%" height={230}>
                <BarChart data={analytics.buckets} margin={{ top: 12, left: -20, right: 8 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="range" tick={{ fontSize: 11 }} />
                  <YAxis allowDecimals={false} tick={{ fontSize: 11 }} />
                  <Tooltip />
                  <Bar dataKey="cases" fill="#2456d6" radius={[3, 3, 0, 0]} isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </article>
        </div>

        <details className="chart-data-disclosure">
          <summary>View Distribution Data as a Table</summary>
          <div className="data-table-wrap">
            <table className="data-table">
              <caption>Case counts by verdict and estimated fraud-likelihood band</caption>
              <thead>
                <tr><th scope="col">Band</th><th scope="col">Verdict</th><th scope="col">Case count</th></tr>
              </thead>
              <tbody>
                {analytics.buckets.map(bucket => (
                  <tr key={`verdict-${bucket.range}`}>
                    <th scope="row">{bucket.range}%</th>
                    <td>All verdicts</td>
                    <td>{formatNumber(bucket.cases)}</td>
                  </tr>
                ))}
                {analytics.byVerdict.map(verdict => (
                  <tr key={`verdict-${verdict.name}`}>
                    <th scope="row">All likelihood bands</th>
                    <td>{verdict.label}</td>
                    <td>{formatNumber(verdict.value)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      </section>

      <section className="panel chart-panel pattern-panel" aria-labelledby="pattern-title">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Fraud Verdicts Only</p>
            <h2 id="pattern-title">Assessed Pattern Mix</h2>
          </div>
        </div>
        {analytics.byPattern.length === 0 ? (
          <ResourceState
            compact
            status="empty"
            title="No fraud patterns to chart"
            message="The returned queue contains no cases with a fraud verdict."
          />
        ) : (
          <>
            <div
              className="chart-frame pattern-chart"
              role="img"
              aria-label={`Fraud pattern counts: ${analytics.byPattern.map(item => `${item.name} ${item.value}`).join(', ')}`}
            >
              <ResponsiveContainer width="100%" height={250}>
                <BarChart data={analytics.byPattern} margin={{ top: 20, left: -18, right: 8 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="name" tick={{ fontSize: 11 }} interval={0} angle={-12} textAnchor="end" height={58} />
                  <YAxis allowDecimals={false} tick={{ fontSize: 11 }} />
                  <Tooltip />
                  <Bar dataKey="value" fill="#2456d6" radius={[3, 3, 0, 0]} isAnimationActive={false}>
                    <LabelList dataKey="value" position="top" style={{ fontSize: 11, fill: '#475569' }} />
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
            <details className="chart-data-disclosure">
              <summary>View Pattern Data as a Table</summary>
              <div className="data-table-wrap">
                <table className="data-table">
                  <caption>Fraud-verdict case count by assessed pattern</caption>
                  <thead><tr><th scope="col">Pattern</th><th scope="col">Cases</th></tr></thead>
                  <tbody>
                    {analytics.byPattern.map(pattern => (
                      <tr key={pattern.name}><th scope="row">{pattern.name}</th><td>{formatNumber(pattern.value)}</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          </>
        )}
      </section>

      <section className="panel interpretation-panel" aria-labelledby="interpretation-title">
        <div>
          <p className="eyebrow">Interpretation Limits</p>
          <h2 id="interpretation-title">What This Snapshot Does Not Establish</h2>
        </div>
        <ul>
          <li>Model accuracy, calibration, or drift on current production traffic.</li>
          <li>That a SAR draft was filed or accepted by an authority.</li>
          <li>That recommended actions were approved or executed.</li>
          <li>That this {formatNumber(cases.length)}-case benchmark generalizes beyond its selection process.</li>
        </ul>
      </section>
    </main>
  )
}
