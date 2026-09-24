import { Link, useParams } from 'react-router-dom'
import CaseWorkspace from '../components/CaseWorkspace.jsx'
import ResourceState from '../components/ResourceState.jsx'
import { useFraudLensData } from '../data/FraudLensData.jsx'
import { formatNumber } from '../lib/format.js'

function CasePager({ previousCase, nextCase, queueReady, queueStatus }) {
  if (!queueReady) {
    const message = queueStatus === 'error'
      ? 'Case positions unavailable'
      : queueStatus === 'success'
        ? 'No case positions returned'
        : 'Loading case positions…'
    return (
      <nav className="case-pager" aria-label="Case pagination">
        <span className="pager-status" role="status">{message}</span>
      </nav>
    )
  }

  return (
    <nav className="case-pager" aria-label="Case pagination">
      {previousCase ? (
        <Link
          className="nav-button previous"
          to={`/cases/${encodeURIComponent(previousCase.case_id)}`}
          rel="prev"
        >
          <span aria-hidden="true">←</span>
          <span><small>Previous</small><strong translate="no">{previousCase.case_id}</strong></span>
        </Link>
      ) : (
        <span className="nav-button disabled" aria-disabled="true">
          <span aria-hidden="true">←</span>
          <span><small>Previous</small><strong>None</strong></span>
        </span>
      )}
      {nextCase ? (
        <Link
          className="nav-button next"
          to={`/cases/${encodeURIComponent(nextCase.case_id)}`}
          rel="next"
        >
          <span><small>Next</small><strong translate="no">{nextCase.case_id}</strong></span>
          <span aria-hidden="true">→</span>
        </Link>
      ) : (
        <span className="nav-button disabled" aria-disabled="true">
          <span><small>Next</small><strong>None</strong></span>
          <span aria-hidden="true">→</span>
        </span>
      )}
    </nav>
  )
}

export default function CasePage() {
  const { caseId } = useParams()
  const { casesResource } = useFraudLensData()
  const cases = Array.isArray(casesResource.data) ? casesResource.data : []
  const index = cases.findIndex(item => item.case_id === caseId)
  const previousCase = index > 0 ? cases[index - 1] : null
  const nextCase = index >= 0 && index < cases.length - 1 ? cases[index + 1] : null

  return (
    <main id="main-content" className="case-page" tabIndex={-1}>
      <div className="case-nav">
        <Link to="/cases" className="back-link"><span aria-hidden="true">←</span> Case Queue</Link>
        {casesResource.status === 'success' && cases.length > 0 && index >= 0 && (
          <span className="case-position">
            Position {formatNumber(index + 1)} of {formatNumber(cases.length)}
          </span>
        )}
        <CasePager
          previousCase={previousCase}
          nextCase={nextCase}
          queueReady={casesResource.status === 'success' && cases.length > 0}
          queueStatus={casesResource.status}
        />
      </div>

      {casesResource.status === 'error' && (
        <div className="context-warning" role="status">
          <span>Case positions are unavailable, so previous/next navigation is disabled.</span>
          <button className="button secondary compact-button" type="button" onClick={casesResource.retry}>
            Retry Case Queue
          </button>
        </div>
      )}

      {casesResource.status === 'success' && cases.length > 0 && index === -1 ? (
        <ResourceState
          status="empty"
          title={`Case ${caseId} is not in the returned queue`}
          message="Return to the investigation queue to choose an available case."
        >
          <Link className="button primary" to="/cases">Return to Case Queue</Link>
        </ResourceState>
      ) : (
        <CaseWorkspace key={caseId} caseId={caseId} />
      )}
    </main>
  )
}
