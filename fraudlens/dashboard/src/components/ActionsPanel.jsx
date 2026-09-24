import { actionKey, getApprovalState, getManualActions } from '../lib/case.js'
import { titleCaseToken } from '../lib/format.js'

function routeLabel(route) {
  if (route === 'auto') return 'Auto'
  if (route === 'L1' || route === 'L2') return `${route} Approval`
  return titleCaseToken(route || 'Route not supplied')
}

function routeClass(route) {
  const value = String(route || '').trim()
  return value === 'auto' || value === 'L1' || value === 'L2' ? value : 'unknown'
}

function ActionList({ actions, emptyLabel }) {
  const items = Array.isArray(actions) ? actions : []
  if (items.length === 0) {
    return <p className="action-empty">{emptyLabel}</p>
  }

  return (
    <ul className="actions">
      {items.map((action, index) => (
        <li key={`${action.action}-${action.route}-${index}`}>
          <div className="action-top">
            <span className="action-name">{titleCaseToken(action.action)}</span>
            <span className={`route ${routeClass(action.route)}`}>
              {routeLabel(action.route)}
            </span>
          </div>
          <span className="action-reason">{action.reason || 'No rationale returned.'}</span>
        </li>
      ))}
    </ul>
  )
}

export default function ActionsPanel({ nba, answer }) {
  const initial = Array.isArray(nba?.initial) ? nba.initial : []
  const final = Array.isArray(nba?.final) ? nba.final : []
  const initialKeys = new Set(initial.map(actionKey))
  const finalKeys = new Set(final.map(actionKey))
  const removed = initial.filter(action => !finalKeys.has(actionKey(action)))
  const added = final.filter(action => !initialKeys.has(actionKey(action)))
  const unchangedCount = [...finalKeys].filter(key => initialKeys.has(key)).length
  const hasDelta = removed.length > 0 || added.length > 0
  const recordedChange = nba?.what_changed
    && String(nba.what_changed).trim().toLowerCase() !== 'nothing'
    ? String(nba.what_changed)
    : null
  const manualActions = getManualActions(nba)
  const approvalState = getApprovalState(answer)

  return (
    <div className="actions-module">
      <div className="actions-grid">
        <section className="action-snapshot" aria-labelledby="initial-actions-title">
          <div className="snapshot-heading">
            <span>Initial Snapshot</span>
            <strong id="initial-actions-title">Before Evidence</strong>
          </div>
          <ActionList actions={initial} emptyLabel="No initial action was returned." />
        </section>
        <section className="action-snapshot final" aria-labelledby="final-actions-title">
          <div className="snapshot-heading">
            <span>Final Snapshot</span>
            <strong id="final-actions-title">After Available Evidence</strong>
          </div>
          <ActionList actions={final} emptyLabel="No final action was returned." />
        </section>
      </div>

      <section className="action-delta" aria-labelledby="action-delta-title">
        <div className="delta-heading">
          <div>
            <p className="eyebrow">Actual Delta</p>
            <h3 id="action-delta-title">Initial vs. Final Recommendations</h3>
          </div>
          <span className={hasDelta ? 'delta-chip changed' : 'delta-chip'}>
            {hasDelta ? 'Changed' : 'No Action-List Change'}
          </span>
        </div>

        {hasDelta ? (
          <div className="delta-columns">
            <div>
              <h4>Removed or rerouted from initial</h4>
              {removed.length > 0 ? (
                <ul>
                  {removed.map(action => (
                    <li key={`removed-${actionKey(action)}`}>
                      {titleCaseToken(action.action)} · {routeLabel(action.route)}
                    </li>
                  ))}
                </ul>
              ) : <p>None</p>}
            </div>
            <div>
              <h4>Added or rerouted in final</h4>
              {added.length > 0 ? (
                <ul>
                  {added.map(action => (
                    <li key={`added-${actionKey(action)}`}>
                      {titleCaseToken(action.action)} · {routeLabel(action.route)}
                    </li>
                  ))}
                </ul>
              ) : <p>None</p>}
            </div>
          </div>
        ) : (
          <p className="delta-empty">
            The final action list matches the initial action list, including route labels.
          </p>
        )}

        <p className="delta-summary">
          <strong>{unchangedCount} unchanged</strong>
          {recordedChange && (
            <>
              {' · '}Recorded run narrative: {recordedChange}
              {nba?.initial !== undefined && ' Narrative may rely on simulated evidence where noted.'}
            </>
          )}
        </p>
        {recordedChange && !hasDelta && (
          <p className="delta-warning" role="note">
            The narrative mentions change, but the recorded action and route lists are identical.
            Treat the narrative as unverified until the backend supplies a matching transition.
          </p>
        )}
      </section>

      {manualActions.length > 0 && (
        <section className="approval-gate" aria-label="Human approval gate">
          <div>
            <strong>
              Approval state:{' '}
              {approvalState ? titleCaseToken(approvalState.value) : 'not supplied'}
            </strong>
            <p>
              {manualActions.length} non-auto{' '}
              {manualActions.length === 1 ? 'route requires' : 'routes require'} human approval. This
              read-only workspace records no approval or execution event of its own.
              {approvalState ? ` State source: ${approvalState.source}.` : ' The API did not return a decision state.'}
            </p>
          </div>
          <div className="route-stack">
            {manualActions.map(action => (
              <span className={`route ${routeClass(action.route)}`} key={`approval-${actionKey(action)}`}>
                {routeLabel(action.route)} · {titleCaseToken(action.action)}
              </span>
            ))}
          </div>
        </section>
      )}
    </div>
  )
}
