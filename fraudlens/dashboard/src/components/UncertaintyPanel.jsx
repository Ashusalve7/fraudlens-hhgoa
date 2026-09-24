import { getApprovalState, getManualActions } from '../lib/case.js'
import { formatNumber, formatPercent, titleCaseToken } from '../lib/format.js'

function suppliedEvidenceConfidence(explanation) {
  const value = explanation?.evidence_confidence?.value ?? explanation?.evidence_confidence
  const number = Number(value)
  if (Number.isFinite(number) && number >= 0 && number <= 1) {
    return {
      value: formatPercent(number),
      detail: 'Value supplied by the explanation response; calibration was not established.',
    }
  }
  return {
    value: 'Not scored',
    detail: 'The API supplies evidence claims, but not a calibrated confidence score.',
  }
}

function suppliedApprovalState(answer) {
  const state = getApprovalState(answer)
  return state ? titleCaseToken(state.value) : null
}

function routeClass(route) {
  const value = String(route || '').trim()
  return value === 'auto' || value === 'L1' || value === 'L2' ? value : 'unknown'
}

export default function UncertaintyPanel({ caseRecord, answer, explanationResource }) {
  const explanation = explanationResource.data
  const manualActions = getManualActions(answer.next_best_actions)
  const evidenceConfidence = suppliedEvidenceConfidence(explanation)
  const approvalState = suppliedApprovalState(answer)

  let readinessTitle = 'No route returned'
  let readinessDetail = 'The case response does not include a final action route.'

  if (manualActions.length > 0) {
    readinessTitle = approvalState || 'Approval state unavailable'
    readinessDetail = approvalState
      ? 'Approval state was supplied by the recorded case response.'
      : 'A non-auto route requires human approval, but the API did not supply a decision state.'
  } else if (answer.next_best_actions?.final?.length) {
    readinessTitle = approvalState || 'No human route returned'
    readinessDetail = approvalState
      ? 'Approval state was supplied by the recorded case response.'
      : 'The recorded final actions are all marked auto; no execution status was returned.'
  }

  const similarOutcomes = caseRecord.similar_case_outcomes
    || caseRecord.similar_prior_case_outcomes
    || []

  return (
    <aside className="panel uncertainty-panel" aria-labelledby="uncertainty-title">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Decision Context</p>
          <h2 id="uncertainty-title">Uncertainty, Separated</h2>
        </div>
        <span className="neutral-chip">Not one score</span>
      </div>

      <div className="uncertainty-metrics">
        <section className="uncertainty-metric fraud" aria-labelledby="likelihood-label">
          <span className="metric-index" aria-hidden="true">01</span>
          <div>
            <h3 id="likelihood-label">Fraud Likelihood</h3>
            <strong>{formatPercent(caseRecord.fraud_probability)}</strong>
            <p>Model-estimated probability—not a finding of fact.</p>
          </div>
        </section>

        <section className="uncertainty-metric evidence" aria-labelledby="confidence-label">
          <span className="metric-index" aria-hidden="true">02</span>
          <div>
            <h3 id="confidence-label">Evidence Confidence</h3>
            <strong>
              {explanationResource.status === 'loading'
                ? 'Loading…'
                : explanationResource.status === 'error'
                  ? 'Unavailable'
                  : evidenceConfidence.value}
            </strong>
            <p>
              {explanationResource.status === 'loading'
                ? 'Reading the explanation response…'
                : explanationResource.status === 'error'
                  ? 'The explanation request failed; claim count below comes from the case detail.'
                  : evidenceConfidence.detail}
            </p>
            <span className="metric-foot">
              {formatNumber(caseRecord.evidence?.length || 0)} recorded claims ·{' '}
              {formatNumber(Array.isArray(similarOutcomes) ? similarOutcomes.length : 0)} outcome records
            </span>
          </div>
        </section>

        <section className="uncertainty-metric readiness" aria-labelledby="readiness-label">
          <span className="metric-index" aria-hidden="true">03</span>
          <div>
            <h3 id="readiness-label">Decision Readiness</h3>
            <strong>{readinessTitle}</strong>
            <p>{readinessDetail}</p>
            {manualActions.length > 0 ? (
              <div className="route-stack" aria-label="Routes requiring approval">
                {manualActions.map(action => (
                  <span className={`route ${routeClass(action.route)}`} key={`${action.action}-${action.route}`}>
                    {action.route} · {titleCaseToken(action.action)}
                  </span>
                ))}
              </div>
            ) : (
              <span className="metric-foot">This dashboard does not execute recommended actions.</span>
            )}
          </div>
        </section>
      </div>

      <p className="uncertainty-footnote">
        A high likelihood does not imply high evidence confidence or completed approval.
      </p>
    </aside>
  )
}
