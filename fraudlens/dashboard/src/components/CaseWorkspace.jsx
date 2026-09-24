import ActionsPanel from './ActionsPanel.jsx'
import CaseTimeline from './CaseTimeline.jsx'
import EvidenceList from './EvidenceList.jsx'
import EvidenceRequests from './EvidenceRequests.jsx'
import InvestGraph from './InvestGraph.jsx'
import ResourceState from './ResourceState.jsx'
import SarDraft from './SarDraft.jsx'
import ScoreExplanation from './ScoreExplanation.jsx'
import SimilarCases from './SimilarCases.jsx'
import UncertaintyPanel from './UncertaintyPanel.jsx'
import { useCaseDetail, useCaseExplanation } from '../data/FraudLensData.jsx'
import { getFinalActions, getRiskBand, getStatusLabel, getVerdictLabel } from '../lib/case.js'
import {
  formatCurrency,
  formatDateTime,
  formatLatency,
  formatNumber,
  formatPercent,
  pluralize,
  titleCaseToken,
} from '../lib/format.js'

const TRIGGER_TITLES = {
  risk_score: 'Risk-Score Alert',
  customer_report: 'Customer Report',
  analyst_request: 'Analyst Review Request',
}

function SummaryStat({ label, value, detail }) {
  return (
    <article className="summary-stat">
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{detail}</small>
    </article>
  )
}

export default function CaseWorkspace({ caseId }) {
  const detailResource = useCaseDetail(caseId)
  const explanationResource = useCaseExplanation(caseId)

  if (detailResource.status === 'loading') {
    return (
      <section className="panel case-loading" aria-labelledby="case-loading-title">
        <h1 id="case-loading-title" className="sr-only">Loading case {caseId}</h1>
        <ResourceState
          status="loading"
          title={`Loading ${caseId}…`}
          message="Reading the recorded investigation, action snapshots, and evidence claims."
        />
        <div className="skeleton-block" aria-hidden="true" />
        <div className="skeleton-line" aria-hidden="true" />
        <div className="skeleton-line medium" aria-hidden="true" />
      </section>
    )
  }

  if (detailResource.status === 'error') {
    return (
      <section className="panel case-loading" aria-labelledby="case-error-title">
        <h1 id="case-error-title" className="sr-only">Case {caseId} unavailable</h1>
        <ResourceState
          status="error"
          title={`Case ${caseId} could not be loaded`}
          message={`${detailResource.error} Check the case response, then retry.`}
          actionLabel="Retry Case Detail"
          onAction={detailResource.retry}
        />
      </section>
    )
  }

  const answer = detailResource.data
  if (!answer?.case) {
    return (
      <ResourceState
        status="empty"
        title={`Case ${caseId} returned no case record`}
        message="The API response did not include the fields required by this workspace."
        actionLabel="Retry Case Detail"
        onAction={detailResource.retry}
      />
    )
  }

  const caseRecord = answer.case
  const affectedTransactions = Array.isArray(caseRecord.affected_txn_ids)
    ? caseRecord.affected_txn_ids
    : []
  const connectedCards = Array.isArray(caseRecord.connected_card_ids) ? caseRecord.connected_card_ids : []
  const connectedDevices = Array.isArray(caseRecord.connected_device_profiles)
    ? caseRecord.connected_device_profiles
    : []
  const evidence = Array.isArray(caseRecord.evidence) ? caseRecord.evidence : []
  const risk = getRiskBand(caseRecord.fraud_probability)
  const finalActions = getFinalActions(answer.next_best_actions)
  const topAction = finalActions[0]
  const triggerTitle = TRIGGER_TITLES[answer.trigger_type] || 'Investigation'
  const caseStatus = getStatusLabel(caseRecord.status)

  return (
    <div className="case-workspace">
      <header className={`case-hero risk-${risk.key}`}>
        <div className="case-hero-top">
          <div className="case-identity">
            <span className="case-id" translate="no">{answer.case_id || caseId}</span>
            <span className={`verdict ${caseRecord.verdict || 'uncertain'}`}>
              {getVerdictLabel(caseRecord.verdict)}
            </span>
            <span className="neutral-chip">{caseStatus}</span>
          </div>
          <span className={`risk-chip ${risk.key}`}>{risk.label} estimated risk</span>
        </div>
        <h1>{triggerTitle}</h1>
        {answer.trigger_text && <blockquote className="trigger-quote">{answer.trigger_text}</blockquote>}
        <p className="hero-summary">
          {caseRecord.summary || 'No case summary was supplied.'}
        </p>
        <dl className="hero-meta">
          <div><dt>Opened</dt><dd>{formatDateTime(answer.opened_at)}</dd></div>
          <div><dt>Flagged transaction</dt><dd translate="no">{answer.flagged_txn_id || caseRecord.first_suspicious_txn_id || 'Not supplied'}</dd></div>
          <div><dt>Case-file graph ref.</dt><dd translate="no">{caseRecord.graph_case_id || 'Not supplied'}</dd></div>
          <div><dt>Recorded run</dt><dd>{pluralize(answer.tool_calls, 'tool call')} · {formatLatency(answer.latency_s)}</dd></div>
        </dl>
      </header>

      <div className="workspace-primary">
        <InvestGraph explanationResource={explanationResource} caseId={caseId} />
        <UncertaintyPanel
          caseRecord={caseRecord}
          answer={answer}
          explanationResource={explanationResource}
        />
      </div>

      <section className="summary-stats" aria-label="Case summary metrics">
        <SummaryStat
          label="Fraud Likelihood"
          value={formatPercent(caseRecord.fraud_probability)}
          detail="Model probability"
        />
        <SummaryStat
          label="Assessed Pattern"
          value={titleCaseToken(caseRecord.pattern)}
          detail={caseRecord.pattern_description || 'Pattern description not supplied'}
        />
        <SummaryStat
          label="Episode Exposure"
          value={formatCurrency(caseRecord.exposure_usd)}
          detail={pluralize(affectedTransactions.length, 'transaction')}
        />
        <SummaryStat
          label="Connected Entities"
          value={formatNumber(connectedCards.length + connectedDevices.length)}
          detail={`${formatNumber(connectedCards.length)} cards · ${formatNumber(connectedDevices.length)} devices`}
        />
      </section>

      <section className="panel decision-panel" aria-labelledby="decision-title">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Policy Recommendation</p>
            <h2 id="decision-title">Initial and Final Actions</h2>
          </div>
          <span className="recommendation-chip">Recommendation only</span>
        </div>
        <div className="top-action">
          <span>Top final recommendation</span>
          <strong>{topAction ? titleCaseToken(topAction.action) : 'No final action returned'}</strong>
          <p>{topAction?.reason || 'No rationale was returned for a final action.'}</p>
        </div>
        <ActionsPanel nba={answer.next_best_actions || {}} />
      </section>

      <div className="evidence-grid">
        <section className="panel evidence-panel" aria-labelledby="evidence-title">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Supporting Record</p>
              <h2 id="evidence-title">Evidence Claims</h2>
            </div>
            <span className="neutral-chip">{pluralize(evidence.length, 'claim')}</span>
          </div>
          <EvidenceList items={evidence} />
        </section>
        <SimilarCases caseRecord={caseRecord} explanation={explanationResource.data} />
      </div>

      <ScoreExplanation
        explanationResource={explanationResource}
        caseRecord={caseRecord}
      />

      <div className="supporting-grid">
        <EvidenceRequests requests={answer.evidence_requests} />
        <CaseTimeline states={answer._states} />
      </div>

      <SarDraft answer={answer} />

      <section className="panel stop-reason" aria-labelledby="stop-reason-title">
        <div>
          <p className="eyebrow">Run Termination</p>
          <h2 id="stop-reason-title">Recorded Stop Reason</h2>
        </div>
        <p>{answer.stop_reason || 'No stop reason was supplied.'}</p>
      </section>
    </div>
  )
}
