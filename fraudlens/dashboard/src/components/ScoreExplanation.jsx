import { useState } from 'react'
import { formatDecimal, formatNumber, formatPercent, titleCaseToken } from '../lib/format.js'
import ResourceState from './ResourceState.jsx'

function contributionValue(value) {
  if (value === null || value === undefined || value === '') return titleCaseToken(value)
  const number = Number(value)
  return Number.isFinite(number) ? formatDecimal(number, 3) : titleCaseToken(value)
}

export default function ScoreExplanation({ explanationResource, caseRecord }) {
  const [open, setOpen] = useState(false)
  const explanation = explanationResource.data
  const contributions = Array.isArray(explanation?.contributions) ? explanation.contributions : []
  const maxAbs = Math.max(...contributions.map(item => Math.abs(Number(item.contribution) || 0)), 0.5)
  const towardFraud = contributions.filter(item => Number(item.contribution) > 0).length
  const model = explanation?.model
  const similarCount = Array.isArray(explanation?.similar_prior_cases)
    ? explanation.similar_prior_cases.length
    : Array.isArray(caseRecord?.similar_prior_cases)
      ? caseRecord.similar_prior_cases.length
      : 0

  return (
    <section className="panel explanation-panel" aria-labelledby="explanation-title">
      <div className="section-heading explanation-heading">
        <div>
          <p className="eyebrow">Model Explanation</p>
          <h2 id="explanation-title">Why This Score?</h2>
        </div>
        {explanationResource.status === 'success' && (
          <button
            className="button secondary compact-button"
            type="button"
            aria-expanded={open}
            aria-controls="explanation-details"
            onClick={() => setOpen(current => !current)}
          >
            {open ? 'Hide Breakdown' : 'Show Breakdown'}
          </button>
        )}
      </div>

      {explanationResource.status === 'loading' && (
        <ResourceState
          status="loading"
          title="Loading score explanation…"
          message="Reading model contributions and feature values from the API."
        />
      )}

      {explanationResource.status === 'error' && (
        <ResourceState
          status="error"
          title="Score explanation unavailable"
          message={`${explanationResource.error} The recorded case and any device traversal remain available.`}
          actionLabel="Retry Explanation"
          onAction={explanationResource.retry}
        />
      )}

      {explanationResource.status === 'success' && !explanation && (
        <ResourceState
          status="empty"
          title="No explanation returned"
          message="The API responded without a score explanation for this case."
        />
      )}

      {explanationResource.status === 'success' && explanation && (
        <>
          <p className="explanation-summary">
            The API returned a logistic-model explanation for this case. Feature contributions show
            each value’s push in log-odds; they are not independent proof of fraud.
          </p>

          {model && (
            <dl className="model-facts" aria-label="Model metadata returned by the API">
              <div>
                <dt>Training set</dt>
                <dd>{model.trained_on || 'Not supplied'}</dd>
              </div>
              <div>
                <dt>Reported holdout AUC</dt>
                <dd>{formatDecimal(model.holdout_auc, 3)}</dd>
              </div>
              <div>
                <dt>Exam prior</dt>
                <dd>{formatPercent(model.exam_prior)}</dd>
              </div>
              <div>
                <dt>Temperature</dt>
                <dd>{formatDecimal(model.temperature, 3)}</dd>
              </div>
            </dl>
          )}

          {open && (
            <div id="explanation-details" className="explanation-details">
              {contributions.length === 0 ? (
                <ResourceState
                  compact
                  status="empty"
                  title="No feature contributions returned"
                  message="The explanation object contains no contribution rows."
                />
              ) : (
                <div
                  className="data-table-wrap"
                  tabIndex={0}
                  aria-label="Scrollable feature contribution table"
                >
                  <table className="data-table contribution-table">
                    <caption>Feature values and their contribution direction</caption>
                    <thead>
                      <tr>
                        <th scope="col">Feature</th>
                        <th scope="col">Value</th>
                        <th scope="col">Contribution</th>
                        <th scope="col">Direction</th>
                      </tr>
                    </thead>
                    <tbody>
                      {contributions.map(item => {
                        const magnitude = Math.abs(Number(item.contribution) || 0)
                        const width = Math.max(2, (magnitude / maxAbs) * 100)
                        return (
                          <tr key={item.feature || item.label}>
                            <th scope="row">{item.label || item.feature}</th>
                            <td>{contributionValue(item.value)}</td>
                            <td>
                              <div className="contribution-cell" title={`Contribution ${formatDecimal(item.contribution, 3)}`}>
                                <span className="contrib-track" aria-hidden="true">
                                  <i className={`fill ${item.toward === 'fraud' ? 'fraud' : 'legit'}`} style={{ width: `${width}%` }} />
                                </span>
                                <span>{formatDecimal(item.contribution, 3)}</span>
                              </div>
                            </td>
                            <td>
                              <span className={`direction ${item.toward === 'fraud' ? 'fraud' : 'legitimate'}`}>
                                {item.toward === 'fraud' ? 'Toward fraud' : 'Toward legitimate'}
                              </span>
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              )}
              <p className="explanation-footnote">
                {formatNumber(towardFraud)} of {formatNumber(contributions.length)} features push
                toward fraud · {formatNumber(explanation.n_evidence ?? caseRecord.evidence?.length ?? 0)}
                {' '}evidence items returned · {formatNumber(similarCount)} similar case IDs.
              </p>
            </div>
          )}
        </>
      )}
    </section>
  )
}
