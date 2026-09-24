import { useEffect, useMemo, useState } from 'react'
import ResourceState from './ResourceState.jsx'

const MAX_VISIBLE_NODES = 9

const NODE_LABELS = {
  case: 'Current case',
  customer: 'Customer',
  card: 'Card',
  transaction: 'Flagged transaction',
  device: 'Device profile',
  connected_card: 'Connected card',
  region: 'Billing region',
  prior_case: 'Prior case',
  unresolved: 'Referenced entity',
}

function normalizeGraph(graph, caseId) {
  const nodes = []
  const nodeById = new Map()

  for (const rawNode of Array.isArray(graph?.nodes) ? graph.nodes : []) {
    if (!rawNode?.id || nodeById.has(rawNode.id)) continue
    const node = {
      id: String(rawNode.id),
      type: NODE_LABELS[rawNode.type] ? rawNode.type : 'unresolved',
      label: String(rawNode.label || rawNode.id),
    }
    nodeById.set(node.id, node)
    nodes.push(node)
  }

  const edges = []
  const edgeKeys = new Set()
  for (const rawEdge of Array.isArray(graph?.edges) ? graph.edges : []) {
    if (!rawEdge?.from || !rawEdge?.to) continue
    const from = String(rawEdge.from)
    const to = String(rawEdge.to)
    const key = `${from}::${to}::${rawEdge.label || ''}`
    if (edgeKeys.has(key)) continue
    edgeKeys.add(key)

    for (const endpoint of [from, to]) {
      if (nodeById.has(endpoint)) continue
      const isCurrentCase = endpoint === caseId
      const node = {
        id: endpoint,
        type: isCurrentCase ? 'case' : 'unresolved',
        label: isCurrentCase ? endpoint : `Referenced entity ${endpoint}`,
      }
      nodeById.set(endpoint, node)
      nodes.push(node)
    }

    edges.push({
      from,
      to,
      label: String(rawEdge.label || 'related to'),
    })
  }

  return { nodes, edges }
}

function shortNodeLabel(node) {
  if (node.type === 'transaction') return node.label.replace(/^\$/, '$')
  if (node.id.length <= 11) return node.id
  return `${node.id.slice(0, 10)}…`
}

function buildLayout(nodes) {
  const width = 760
  const height = 370
  const centerY = height / 2
  const columns = [
    { types: ['case', 'prior_case'], x: 75 },
    { types: ['customer'], x: 225 },
    { types: ['card'], x: 380 },
    { types: ['transaction'], x: 525 },
    { types: ['device', 'connected_card', 'region', 'unresolved'], x: 680 },
  ]
  const positions = {}

  columns.forEach(column => {
    const columnNodes = nodes.filter(node => column.types.includes(node.type))
    if (columnNodes.length === 0) return
    const availableHeight = height - 70
    const spacing = Math.min(66, availableHeight / Math.max(columnNodes.length - 1, 1))
    const usedHeight = spacing * Math.max(columnNodes.length - 1, 0)
    const startY = centerY - usedHeight / 2

    columnNodes.forEach((node, index) => {
      positions[node.id] = [column.x, startY + index * spacing]
    })
  })

  const unpositioned = nodes.filter(node => !positions[node.id])
  unpositioned.forEach((node, index) => {
    positions[node.id] = [680, 38 + index * 34]
  })

  return { positions, width, height }
}

function edgePath(from, to) {
  const midpointX = (from[0] + to[0]) / 2
  return `M ${from[0]} ${from[1]} C ${midpointX} ${from[1]}, ${midpointX} ${to[1]}, ${to[0]} ${to[1]}`
}

function edgeLabelPosition(from, to) {
  return [(from[0] + to[0]) / 2, (from[1] + to[1]) / 2 - 8]
}

export default function InvestGraph({ explanationResource, caseId }) {
  const [showAll, setShowAll] = useState(false)
  const [view, setView] = useState('graph')

  useEffect(() => {
    setShowAll(false)
    setView('graph')
  }, [caseId, explanationResource.data])

  const normalized = useMemo(
    () => normalizeGraph(explanationResource.data?.graph, caseId),
    [caseId, explanationResource.data],
  )
  const visibleNodes = showAll
    ? normalized.nodes
    : normalized.nodes.slice(0, MAX_VISIBLE_NODES)
  const visibleIds = new Set(visibleNodes.map(node => node.id))
  const visibleEdges = normalized.edges.filter(
    edge => visibleIds.has(edge.from) && visibleIds.has(edge.to),
  )
  const hiddenCount = normalized.nodes.length - visibleNodes.length
  const hiddenEdgeCount = normalized.edges.length - visibleEdges.length
  const layout = buildLayout(visibleNodes)

  if (explanationResource.status === 'loading') {
    return (
      <section className="panel graph-panel" aria-labelledby="graph-title">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Entity Context</p>
            <h2 id="graph-title">Investigation Graph</h2>
          </div>
        </div>
        <ResourceState
          status="loading"
          title="Loading graph context…"
          message="Reading the nodes and relationships returned with this case explanation."
        />
      </section>
    )
  }

  if (explanationResource.status === 'error') {
    return (
      <section className="panel graph-panel" aria-labelledby="graph-title">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Entity Context</p>
            <h2 id="graph-title">Investigation Graph</h2>
          </div>
        </div>
        <ResourceState
          status="error"
          title="Graph context unavailable"
          message={explanationResource.error}
          actionLabel="Retry Explanation"
          onAction={explanationResource.retry}
        />
      </section>
    )
  }

  if (normalized.nodes.length === 0) {
    return (
      <section className="panel graph-panel" aria-labelledby="graph-title">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Entity Context</p>
            <h2 id="graph-title">Investigation Graph</h2>
          </div>
        </div>
        <ResourceState
          status="empty"
          title="No graph entities returned"
          message="The explanation response did not include a graph for this case."
        />
      </section>
    )
  }

  const typesPresent = [...new Set(normalized.nodes.map(node => node.type))]
  const description = hiddenCount > 0
    ? `Graph showing ${visibleNodes.length} of ${normalized.nodes.length} entities. ${hiddenCount} entities and ${hiddenEdgeCount} relationships are hidden until all entities are shown.`
    : `Graph showing all ${normalized.nodes.length} entities and ${normalized.edges.length} relationships.`

  return (
    <section className="panel graph-panel" aria-labelledby="graph-title">
      <div className="section-heading graph-heading">
        <div>
          <p className="eyebrow">Entity Context</p>
          <h2 id="graph-title">Investigation Graph</h2>
        </div>
        <div className="view-switcher" role="group" aria-label="Graph presentation">
          <button
            type="button"
            className={view === 'graph' ? 'active' : ''}
            aria-pressed={view === 'graph'}
            onClick={() => setView('graph')}
          >
            Graph View
          </button>
          <button
            type="button"
            className={view === 'table' ? 'active' : ''}
            aria-pressed={view === 'table'}
            onClick={() => setView('table')}
          >
            Table View
          </button>
        </div>
      </div>

      <div className="graph-scope" aria-live="polite">
        <span>
          Showing <strong>{visibleNodes.length}</strong> of {normalized.nodes.length} entities
        </span>
        <span>{normalized.edges.length} relationships returned</span>
      </div>

      {view === 'graph' ? (
        <>
          <div className="graph-canvas">
            <svg
              viewBox={`0 0 ${layout.width} ${layout.height}`}
              width="100%"
              role="img"
              aria-labelledby="graph-svg-title graph-svg-desc"
              focusable="false"
            >
              <title id="graph-svg-title">Investigation graph for {caseId}</title>
              <desc id="graph-svg-desc">{description}</desc>
              {visibleEdges.map((edge, index) => {
                const from = layout.positions[edge.from]
                const to = layout.positions[edge.to]
                if (!from || !to) return null
                const [labelX, labelY] = edgeLabelPosition(from, to)
                return (
                  <g key={`${edge.from}-${edge.to}-${edge.label}-${index}`}>
                    <path d={edgePath(from, to)} className="g-edge" />
                    <text x={labelX} y={labelY} textAnchor="middle" className="g-edge-label">
                      {edge.label}
                    </text>
                  </g>
                )
              })}
              {visibleNodes.map(node => {
                const [x, y] = layout.positions[node.id]
                const radius = node.type === 'transaction' ? 21 : node.type === 'case' ? 18 : 16
                return (
                  <g key={node.id} className="graph-node">
                    <title>{`${NODE_LABELS[node.type]}: ${node.label}`}</title>
                    <circle cx={x} cy={y} r={radius} className={`g-node g-${node.type}`} />
                    <text x={x} y={y + 3} textAnchor="middle" className="g-node-label">
                      {shortNodeLabel(node)}
                    </text>
                    <text x={x} y={y + radius + 14} textAnchor="middle" className="g-type-label">
                      {NODE_LABELS[node.type]}
                    </text>
                  </g>
                )
              })}
            </svg>
          </div>

          {hiddenCount > 0 && (
            <div className="graph-truncation">
              <p>
                {hiddenCount} {hiddenCount === 1 ? 'entity is' : 'entities are'} hidden to keep this
                view readable. {hiddenEdgeCount} related{' '}
                {hiddenEdgeCount === 1 ? 'relationship is' : 'relationships are'} omitted.
              </p>
              <button className="button secondary" type="button" onClick={() => setShowAll(true)}>
                Show +{hiddenCount} More
              </button>
            </div>
          )}
          {showAll && normalized.nodes.length > MAX_VISIBLE_NODES && (
            <button className="button text-button" type="button" onClick={() => setShowAll(false)}>
              Show Compact View
            </button>
          )}

          <div className="legend" aria-label="Graph legend">
            {typesPresent.map(type => (
              <span className="legend-item" key={type}>
                <i className={`legend-swatch ${type}`} aria-hidden="true" />
                {NODE_LABELS[type]}
              </span>
            ))}
          </div>
        </>
      ) : (
        <div className="graph-table-stack">
          <div className="data-table-wrap">
            <table className="data-table">
              <caption>All graph entities returned for {caseId}</caption>
              <thead>
                <tr>
                  <th scope="col">Entity</th>
                  <th scope="col">Type</th>
                  <th scope="col">Label</th>
                  <th scope="col">Compact view</th>
                </tr>
              </thead>
              <tbody>
                {normalized.nodes.map((node, index) => (
                  <tr key={node.id}>
                    <th scope="row" translate="no">{node.label}</th>
                    <td>{NODE_LABELS[node.type]}</td>
                    <td>{node.id}</td>
                    <td>{index < MAX_VISIBLE_NODES ? 'Shown' : 'Hidden'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="data-table-wrap">
            <table className="data-table">
              <caption>All graph relationships returned for {caseId}</caption>
              <thead>
                <tr>
                  <th scope="col">Source</th>
                  <th scope="col">Relationship</th>
                  <th scope="col">Target</th>
                </tr>
              </thead>
              <tbody>
                {normalized.edges.length === 0 ? (
                  <tr><td colSpan="3">No relationships returned.</td></tr>
                ) : normalized.edges.map((edge, index) => (
                  <tr key={`${edge.from}-${edge.to}-${edge.label}-${index}`}>
                    <th scope="row" translate="no">{edge.from}</th>
                    <td>{edge.label}</td>
                    <td translate="no">{edge.to}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  )
}
