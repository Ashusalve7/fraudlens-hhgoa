import { useState } from 'react'
import { fetchRing } from '../api.js'
import ResourceState from './ResourceState.jsx'
import { formatNumber } from '../lib/format.js'

export default function RingView({ txnId }) {
  const [ring, setRing] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  async function load() {
    setLoading(true)
    setError(null)
    try {
      setRing(await fetchRing(txnId))
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setLoading(false)
    }
  }

  const cards = Array.isArray(ring?.cards) ? ring.cards : []
  const centerX = 330
  const centerY = 170
  const radius = 125

  return (
    <section className="panel ring-panel" aria-labelledby="device-neighborhood-title">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Optional Traversal</p>
          <h2 id="device-neighborhood-title">Device Neighborhood</h2>
        </div>
      </div>

      {!ring && !loading && !error && (
        <ResourceState
          status="empty"
          title="Neighborhood not requested"
          message="Load the graph traversal only when this wider device context is needed."
        >
          <button className="button secondary" type="button" onClick={load}>
            Load Device Neighborhood
          </button>
        </ResourceState>
      )}

      {loading && <ResourceState status="loading" title="Loading device neighborhood…" />}
      {error && (
        <ResourceState
          status="error"
          title="Device neighborhood unavailable"
          message={error}
          actionLabel="Retry Traversal"
          onAction={load}
        />
      )}

      {ring && cards.length === 0 && (
        <ResourceState
          status="empty"
          title="No connected cards returned"
          message="The traversal completed without a connected-card list."
        />
      )}

      {ring && cards.length > 0 && (
        <>
          <svg viewBox="0 0 660 340" width="100%" role="img" aria-label="Device neighborhood graph">
            {cards.map((card, index) => {
              const angle = (2 * Math.PI * index) / cards.length
              const x = centerX + radius * Math.cos(angle)
              const y = centerY + radius * Math.sin(angle)
              return (
                <g key={card}>
                  <line x1={centerX} y1={centerY} x2={x} y2={y} className="edge" />
                  <circle cx={x} cy={y} r="10" className="card-node"><title>{card}</title></circle>
                  <text x={x} y={y + 22} textAnchor="middle">{card}</text>
                </g>
              )
            })}
            <circle cx={centerX} cy={centerY} r="20" className="device-node" />
            <text x={centerX} y={centerY + 36} textAnchor="middle">{ring.device?.device_id || 'Device'}</text>
          </svg>
          <p className="ring-meta">
            {[ring.device?.device_info, ring.device?.os].filter(Boolean).join(' / ') || 'Device metadata not supplied'}
            {' · '}{formatNumber(cards.length)} cards · {formatNumber(ring.n_txns)} transactions ·{' '}
            {formatNumber(ring.prior_cases?.length || 0)} prior cases
          </p>
          <details className="chart-data-disclosure">
            <summary>View Connected Cards as a Table</summary>
            <ul>{cards.map(card => <li key={card} translate="no">{card}</li>)}</ul>
          </details>
        </>
      )}
    </section>
  )
}
