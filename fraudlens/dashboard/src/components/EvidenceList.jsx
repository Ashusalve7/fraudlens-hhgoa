import { useState } from 'react'
import { formatNumber, titleCaseToken } from '../lib/format.js'
import ResourceState from './ResourceState.jsx'

const DEFAULT_VISIBLE_ENTITIES = 6

export default function EvidenceList({ items }) {
  const [expanded, setExpanded] = useState({})
  const evidence = Array.isArray(items) ? items : []

  if (evidence.length === 0) {
    return (
      <ResourceState
        compact
        status="empty"
        title="No evidence claims returned"
        message="The case record does not include a supporting-claim list."
      />
    )
  }

  return (
    <ul className="evidence">
      {evidence.map((item, index) => {
        const source = String(item?.source || 'other').toLowerCase()
        const sourceClass = ['graph', 'customer', 'document'].includes(source) ? source : 'other'
        const entityIds = Array.isArray(item?.entity_ids) ? item.entity_ids : []
        const isExpanded = Boolean(expanded[index])
        const visibleIds = isExpanded ? entityIds : entityIds.slice(0, DEFAULT_VISIBLE_ENTITIES)
        const hiddenCount = entityIds.length - visibleIds.length
        const key = `${item?.ref || source || 'evidence'}-${index}`
        const simulated = item?.simulated === true
          || source === 'customer'
            && String(item?.ref || '').toLowerCase().startsWith('evidence_request')

        return (
          <li key={key} className={`${sourceClass}${simulated ? ' simulated-evidence' : ''}`}>
            <div className="ev-meta">
              <span className="ev-source">{titleCaseToken(item?.source || 'Other')}</span>
              <span className="ev-ref" translate="no">{item?.ref || 'Reference not supplied'}</span>
            </div>
            {simulated && <span className="assumed-label">Assumed evidence · Simulated</span>}
            <p>{item?.claim || 'No claim text returned.'}</p>
            {entityIds.length > 0 && (
              <div className="entity-ids">
                <span className="sr-only">Referenced entities: </span>
                {visibleIds.map((id, idIndex) => <code key={`${id}-${idIndex}`}>{id}</code>)}
                {hiddenCount > 0 && (
                  <button
                    className="inline-action"
                    type="button"
                    aria-label={`Show ${formatNumber(hiddenCount)} more referenced entities for evidence item ${index + 1}`}
                    onClick={() => setExpanded(current => ({ ...current, [index]: true }))}
                  >
                    +{formatNumber(hiddenCount)} more
                  </button>
                )}
              </div>
            )}
          </li>
        )
      })}
    </ul>
  )
}
