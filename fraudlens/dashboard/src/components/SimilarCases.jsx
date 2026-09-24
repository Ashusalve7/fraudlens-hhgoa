import { formatDecimal, titleCaseToken } from '../lib/format.js'
import ResourceState from './ResourceState.jsx'

function normalizeOutcome(record) {
  if (typeof record === 'string') {
    return { caseId: record, outcome: null, similarity: null }
  }
  return {
    caseId: record?.case_id || record?.id || 'Unidentified prior case',
    outcome: record?.outcome || record?.disposition || record?.status || record?.label || null,
    similarity: record?.similarity ?? record?.score ?? null,
  }
}

function similarityLabel(value) {
  if (value === null || value === undefined || value === '') return null
  const number = Number(value)
  if (Number.isFinite(number) && number >= 0 && number <= 1) {
    return `Similarity ${formatDecimal(number, 3)}`
  }
  return `Similarity ${value}`
}

export default function SimilarCases({ caseRecord, explanation }) {
  const outcomeSource = caseRecord.similar_case_outcomes
    || caseRecord.similar_prior_case_outcomes
  const ids = Array.isArray(caseRecord.similar_prior_cases)
    ? caseRecord.similar_prior_cases
    : Array.isArray(explanation?.similar_prior_cases)
      ? explanation.similar_prior_cases
      : []

  const records = Array.isArray(outcomeSource) && outcomeSource.length > 0
    ? outcomeSource
    : ids
  const outcomes = records.map(normalizeOutcome)
  const availableOutcomes = outcomes.filter(item => item.outcome).length

  return (
    <section className="panel similar-panel" aria-labelledby="similar-title">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Case Memory</p>
          <h2 id="similar-title">Similar-Case Outcomes</h2>
        </div>
        <span className="neutral-chip">
          {availableOutcomes} / {outcomes.length} outcomes supplied
        </span>
      </div>

      {outcomes.length === 0 ? (
        <ResourceState
          compact
          status="empty"
          title="No similar cases returned"
          message="The case and explanation responses contain no comparable prior-case references."
        />
      ) : (
        <>
          <p className="similar-intro">
            {availableOutcomes > 0
              ? 'Outcome fields below were supplied by the API.'
              : 'Only prior-case IDs were supplied. No outcome or disposition was inferred.'}
          </p>
          <ul className="similar-list">
            {outcomes.map((item, index) => {
              const similarity = similarityLabel(item.similarity)
              return (
                <li key={`${item.caseId}-${index}`}>
                  <div>
                    <strong translate="no">{item.caseId}</strong>
                    {similarity && <span>{similarity}</span>}
                  </div>
                  <span className={item.outcome ? 'outcome known' : 'outcome missing'}>
                    {item.outcome ? titleCaseToken(item.outcome) : 'Outcome unavailable'}
                  </span>
                </li>
              )
            })}
          </ul>
        </>
      )}
    </section>
  )
}
