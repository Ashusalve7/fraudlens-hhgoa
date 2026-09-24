import { formatDateTime, titleCaseToken } from '../lib/format.js'
import ResourceState from './ResourceState.jsx'

const STATE_DETAILS = {
  TRIGGERED: 'Recorded trigger accepted.',
  CONTEXT_RETRIEVED: 'Transaction and account context recorded.',
  EVIDENCE_GATHERED: 'Supporting claims added to the case bundle.',
  PATTERNS_ASSESSED: 'Pattern assessment recorded.',
  MEMORY_RETRIEVED: 'Prior-case references recorded.',
  NBA_INITIAL: 'Initial policy recommendations recorded.',
  EVIDENCE_REQUESTED: 'An evidence request was inserted; the response is simulated unless separately observed.',
  EVIDENCE_RECEIVED: 'A simulated evidence response was recorded.',
  NBA_FINAL: 'Final policy recommendations recorded.',
  CASE_WRITTEN: 'The case-file write flag was recorded.',
  ANSWER_EXPORTED: 'The answer artifact was exported.',
}

function stateLabel(state) {
  const token = titleCaseToken(state)
  return token === 'Nba' ? 'NBA' : token
}

export default function CaseTimeline({ states, openedAt }) {
  const items = Array.isArray(states) ? states : []

  return (
    <section className="panel timeline-panel" aria-labelledby="timeline-title">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Recorded Run</p>
          <h2 id="timeline-title">Investigation Timeline</h2>
        </div>
        <span className="neutral-chip">Sequence only</span>
      </div>

      {items.length === 0 ? (
        <ResourceState
          compact
          status="empty"
          title="No run sequence returned"
          message="The case response did not include state-transition data."
        />
      ) : (
        <>
          <p className="timeline-context">
            Opened {formatDateTime(openedAt)}. The case file supplies ordered states but no timestamp
            for each transition, so elapsed time is not inferred.
          </p>
          <ol className="case-timeline" aria-label="Recorded investigation sequence">
            {items.map((state, index) => {
              const normalized = String(state || '').toUpperCase()
              const simulated = normalized === 'EVIDENCE_REQUESTED' || normalized === 'EVIDENCE_RECEIVED'
              return (
                <li key={`${state}-${index}`} className={simulated ? 'simulated-state' : ''}>
                  <span className="timeline-index" aria-hidden="true">{index + 1}</span>
                  <div>
                    <strong>{stateLabel(state)}</strong>
                    <span>{STATE_DETAILS[normalized] || 'Recorded state supplied by the case file.'}</span>
                  </div>
                  {simulated && <span className="timeline-simulated">Simulated exchange</span>}
                </li>
              )
            })}
          </ol>
        </>
      )}
    </section>
  )
}
