import { formatNumber, titleCaseToken } from '../lib/format.js'
import ResourceState from './ResourceState.jsx'

export default function EvidenceRequests({ requests }) {
  const items = Array.isArray(requests) ? requests : []

  return (
    <section className="panel evidence-requests" aria-labelledby="evidence-requests-title">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Evidence Gap</p>
          <h2 id="evidence-requests-title">Simulated Evidence Requests</h2>
        </div>
        <span className="simulated-chip">Simulated</span>
      </div>

      {items.length === 0 ? (
        <ResourceState
          compact
          status="empty"
          title="No evidence request recorded"
          message="This case did not include a simulated customer or document exchange."
        />
      ) : (
        <>
          <p className="simulation-note">
            These assumed requests and responses are case-pack artifacts. The dashboard cannot verify
            that an external request was sent or received.
          </p>
          <ol className="request-list">
            {items.map((request, index) => (
              <li key={`${request.type || 'request'}-${index}`}>
                <div className="request-meta">
                  <strong>{titleCaseToken(request.type || 'Evidence request')}</strong>
                  {Number.isFinite(Number(request.asked_after_step)) && (
                    <span>Inserted after run step {formatNumber(request.asked_after_step)}</span>
                  )}
                </div>
                <span className="assumed-label">Assumed response · Simulated</span>
                <p>
                  {request.assumed_response
                    || 'No assumed response was recorded for this request.'}
                </p>
              </li>
            ))}
          </ol>
        </>
      )}
    </section>
  )
}
