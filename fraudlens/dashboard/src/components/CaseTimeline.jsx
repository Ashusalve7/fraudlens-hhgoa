import { titleCaseToken } from '../lib/format.js'
import ResourceState from './ResourceState.jsx'

export default function CaseTimeline({ states }) {
  const items = Array.isArray(states) ? states : []

  return (
    <section className="panel timeline-panel" aria-labelledby="timeline-title">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Recorded Run</p>
          <h2 id="timeline-title">Investigation Timeline</h2>
        </div>
        <span className="neutral-chip">No timestamps</span>
      </div>

      {items.length === 0 ? (
        <ResourceState
          compact
          status="empty"
          title="No run sequence returned"
          message="The case response did not include state-transition data."
        />
      ) : (
        <ol className="case-timeline" aria-label="Recorded investigation sequence">
          {items.map((state, index) => (
            <li key={`${state}-${index}`}>
              <span className="timeline-index" aria-hidden="true">{index + 1}</span>
              <span>{titleCaseToken(state)}</span>
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}
