import { useEffect, useMemo, useState } from 'react'
import ResourceState from './ResourceState.jsx'
import { useDeviceNeighborhood } from '../data/FraudLensData.jsx'
import { formatNumber, pluralize } from '../lib/format.js'

const MAX_VISIBLE_NODES = 9
const MIN_GRAPH_HEIGHT = 390

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

const TYPE_PRIORITY = {
  case: 0,
  transaction: 1,
  device: 2,
  card: 3,
  customer: 4,
  connected_card: 5,
  region: 6,
  prior_case: 7,
  unresolved: 8,
}

function addNode(nodeById, nodes, rawNode, fallbackType = 'unresolved') {
  if (!rawNode?.id) return null
  const id = String(rawNode.id)
  if (nodeById.has(id)) return nodeById.get(id)

  const suppliedType = NODE_LABELS[rawNode.type] ? rawNode.type : fallbackType
  const node = {
    id,
    type: suppliedType,
    label: String(rawNode.label || rawNode.id),
  }
  nodeById.set(id, node)
  nodes.push(node)
  return node
}

function normalizeExplanationGraph(graph, caseId, seed = {}) {
  const nodes = []
  const nodeById = new Map()
  const edges = []
  const edgeKeys = new Set()

  function ensureEdge(from, to, label) {
    const key = `${from}::${to}::${label}`
    if (!from || !to || from === to || edgeKeys.has(key)) return
    edgeKeys.add(key)
    edges.push({ from, to, label })
  }

  // The case is the graph root even when a provider response omits it.
  addNode(nodeById, nodes, { id: caseId, type: 'case', label: caseId }, 'case')
  if (seed.flaggedTxnId) {
    addNode(nodeById, nodes, {
      id: seed.flaggedTxnId,
      type: 'transaction',
      label: seed.flaggedTxnId,
    }, 'transaction')
    ensureEdge(caseId, seed.flaggedTxnId, 'investigates')
  }
  if (seed.customerId) {
    addNode(nodeById, nodes, {
      id: seed.customerId,
      type: 'customer',
      label: seed.customerId,
    }, 'customer')
  }
  if (seed.cardId) {
    addNode(nodeById, nodes, {
      id: seed.cardId,
      type: 'card',
      label: seed.cardId,
    }, 'card')
  }
  if (seed.customerId && seed.cardId) ensureEdge(seed.customerId, seed.cardId, 'owns')
  if (seed.cardId && seed.flaggedTxnId) ensureEdge(seed.cardId, seed.flaggedTxnId, 'made')

  for (const rawNode of Array.isArray(graph?.nodes) ? graph.nodes : []) {
    addNode(nodeById, nodes, rawNode)
  }
  for (const rawEdge of Array.isArray(graph?.edges) ? graph.edges : []) {
    if (!rawEdge?.from || !rawEdge?.to) continue
    const from = String(rawEdge.from)
    const to = String(rawEdge.to)
    if (from === to) continue
    const key = `${from}::${to}::${rawEdge.label || ''}`
    if (edgeKeys.has(key)) continue
    edgeKeys.add(key)

    addNode(nodeById, nodes, {
      id: from,
      type: from === caseId ? 'case' : 'unresolved',
      label: from === caseId ? from : `Referenced entity ${from}`,
    }, from === caseId ? 'case' : 'unresolved')
    addNode(nodeById, nodes, {
      id: to,
      type: to === caseId ? 'case' : 'unresolved',
      label: to === caseId ? to : `Referenced entity ${to}`,
    }, to === caseId ? 'case' : 'unresolved')

    edges.push({
      from,
      to,
      label: String(rawEdge.label || 'related to'),
    })
  }

  return { nodes, edges }
}

function normalizeRingGraph(ring, baseGraph, flaggedTxnId) {
  if (!ring || typeof ring !== 'object') return baseGraph
  const nodes = baseGraph.nodes.map(node => ({ ...node }))
  const nodeById = new Map(nodes.map(node => [node.id, node]))
  const edges = baseGraph.edges.map(edge => ({ ...edge }))
  const edgeKeys = new Set(edges.map(edge => `${edge.from}::${edge.to}::${edge.label}`))
  const deviceId = String(ring.device?.device_id || '').trim()
  const cards = Array.isArray(ring.cards) ? ring.cards : []

  function ensureNode(rawNode, fallbackType = 'unresolved') {
    return addNode(nodeById, nodes, rawNode, fallbackType)
  }

  function ensureEdge(from, to, label) {
    const key = `${from}::${to}::${label}`
    if (!from || !to || from === to || edgeKeys.has(key)) return
    edgeKeys.add(key)
    edges.push({ from, to, label })
  }

  if (deviceId) {
    const device = ensureNode({
      id: deviceId,
      type: 'device',
      label: String(ring.device?.device_info || deviceId),
    }, 'device')
    if (flaggedTxnId) ensureEdge(flaggedTxnId, device.id, 'from device')

    for (const rawCard of cards) {
      const cardId = String(rawCard || '').trim()
      if (!cardId) continue
      const card = ensureNode({ id: cardId, type: 'connected_card', label: cardId }, 'connected_card')
      ensureEdge(device.id, card.id, 'also used by')
    }
  }

  // A ring response can legitimately contain no cards. Keep any explanation-only
  // context rather than discarding it when the wider traversal is empty.
  return { nodes, edges }
}

function shortNodeLabel(node) {
  if (node.type === 'case') return node.id
  if (node.id.length <= 12) return node.id
  return `${node.id.slice(0, 11)}…`
}

function orderedNodes(nodes) {
  return [...nodes].sort((left, right) => {
    const priority = (TYPE_PRIORITY[left.type] ?? 99) - (TYPE_PRIORITY[right.type] ?? 99)
    return priority || left.id.localeCompare(right.id)
  })
}

function selectVisibleNodes(nodes, limit) {
  const ordered = orderedNodes(nodes)
  if (ordered.length <= limit) return ordered

  // Fill compact slots with the case spine first, then related entities. This keeps
  // the primary path visible instead of allowing one high-cardinality type to win.
  const selected = []
  const selectedIds = new Set()
  const add = node => {
    if (!node || selectedIds.has(node.id) || selected.length >= limit) return
    selected.push(node)
    selectedIds.add(node.id)
  }

  ;['case', 'transaction', 'device', 'card', 'customer'].forEach(type => {
    add(ordered.find(node => node.type === type))
  })
  ;['connected_card', 'region', 'prior_case', 'unresolved'].forEach(type => {
    ordered.filter(node => node.type === type).forEach(add)
  })
  ordered.forEach(add)
  return selected
}

function buildLayout(nodes) {
  const width = 820
  const columnX = [88, 270, 455, 645, 760]
  const columns = [
    ['case', 'prior_case'],
    ['customer'],
    ['card'],
    ['transaction'],
    ['device', 'connected_card', 'region', 'unresolved'],
  ]
  const rightColumnCount = nodes.filter(node => columns[4].includes(node.type)).length
  const height = Math.max(MIN_GRAPH_HEIGHT, 92 + Math.max(rightColumnCount - 1, 0) * 54)
  const positions = {}

  columns.forEach((types, columnIndex) => {
    const columnNodes = nodes.filter(node => types.includes(node.type))
    if (columnNodes.length === 0) return
    const spacing = Math.min(62, (height - 80) / Math.max(columnNodes.length - 1, 1))
    const usedHeight = spacing * Math.max(columnNodes.length - 1, 0)
    const startY = (height - usedHeight) / 2
    columnNodes.forEach((node, index) => {
      positions[node.id] = [columnX[columnIndex], startY + index * spacing]
    })
  })

  const unpositioned = nodes.filter(node => !positions[node.id])
  unpositioned.forEach((node, index) => {
    positions[node.id] = [columnX[4], 46 + index * 42]
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

function GraphTable({ normalized, caseId, visibleIds }) {
  return (
    <div className="graph-table-stack">
      <div className="data-table-wrap">
        <table className="data-table">
          <caption>All normalized graph entities for {caseId}</caption>
          <thead>
            <tr>
              <th scope="col">Entity</th>
              <th scope="col">Type</th>
              <th scope="col">Label</th>
              <th scope="col">Compact view</th>
            </tr>
          </thead>
          <tbody>
            {normalized.nodes.map(node => (
              <tr key={node.id}>
                <th scope="row" translate="no">{node.id}</th>
                <td>{NODE_LABELS[node.type]}</td>
                <td>{node.label}</td>
                <td>{visibleIds.has(node.id) ? 'Shown' : 'Hidden'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="data-table-wrap">
        <table className="data-table">
          <caption>All normalized graph relationships for {caseId}</caption>
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
  )
}

export default function InvestGraph({
  explanationResource,
  caseId,
  flaggedTxnId,
  cardId,
  customerId,
}) {
  const [view, setView] = useState('graph')
  const [showAll, setShowAll] = useState(false)
  const [loadNeighborhood, setLoadNeighborhood] = useState(false)

  useEffect(() => {
    setView('graph')
    setShowAll(false)
    setLoadNeighborhood(false)
  }, [caseId, flaggedTxnId])

  useEffect(() => {
    if (explanationResource.status === 'error' && flaggedTxnId) {
      setLoadNeighborhood(true)
    }
  }, [explanationResource.status, flaggedTxnId])

  const explanationGraph = useMemo(
    () => normalizeExplanationGraph(explanationResource.data?.graph, caseId, {
      flaggedTxnId,
      cardId,
      customerId,
    }),
    [cardId, caseId, customerId, explanationResource.data, flaggedTxnId],
  )
  const ringResource = useDeviceNeighborhood(flaggedTxnId, 45, loadNeighborhood)
  const normalized = useMemo(
    () => normalizeRingGraph(ringResource.data, explanationGraph, flaggedTxnId),
    [explanationGraph, flaggedTxnId, ringResource.data],
  )
  const visibleNodes = showAll
    ? orderedNodes(normalized.nodes)
    : selectVisibleNodes(normalized.nodes, MAX_VISIBLE_NODES)
  const visibleIds = new Set(visibleNodes.map(node => node.id))
  const visibleEdges = normalized.edges.filter(
    edge => visibleIds.has(edge.from) && visibleIds.has(edge.to),
  )
  const hiddenCount = normalized.nodes.length - visibleNodes.length
  const hiddenEdgeCount = normalized.edges.length - visibleEdges.length
  const layout = buildLayout(visibleNodes)
  const typesPresent = [...new Set(visibleNodes.map(node => node.type))]
  const ringCards = Array.isArray(ringResource.data?.cards) ? ringResource.data.cards : []
  const description = hiddenCount > 0
    ? `Graph showing ${visibleNodes.length} of ${normalized.nodes.length} normalized entities. ${hiddenCount} entities and ${hiddenEdgeCount} relationships are hidden until all entities are shown.`
    : `Graph showing all ${normalized.nodes.length} normalized entities and ${normalized.edges.length} relationships.`

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
          message="Reading the score explanation before loading the optional device traversal."
        />
      </section>
    )
  }

  if (explanationResource.status === 'error' && ringResource.status !== 'success') {
    if (ringResource.status === 'loading') {
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
            title="Loading device neighborhood fallback…"
            message="The score explanation failed, so FraudLens is loading the separate bounded graph traversal."
          />
        </section>
      )
    }

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
          message={ringResource.status === 'error'
            ? `Score explanation: ${explanationResource.error} Device traversal: ${ringResource.error}`
            : `${explanationResource.error} The wider device traversal is a separate API and was not loaded.`}
          actionLabel={ringResource.status === 'error' ? 'Retry Device Traversal' : 'Retry Explanation'}
          onAction={ringResource.status === 'error' ? ringResource.retry : explanationResource.retry}
        >
          {flaggedTxnId && ringResource.status !== 'error' && (
            <button className="button secondary" type="button" onClick={() => setLoadNeighborhood(true)}>
              Try Device Neighborhood Instead
            </button>
          )}
        </ResourceState>
      </section>
    )
  }

  if (normalized.nodes.length <= 1 && normalized.edges.length === 0) {
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
          title="No graph relationships returned"
          message="The explanation response contained no usable entities, and no device traversal was loaded."
        />
        {flaggedTxnId && (
          <button className="button secondary graph-empty-action" type="button" onClick={() => setLoadNeighborhood(true)}>
            Load Device Neighborhood
          </button>
        )}
      </section>
    )
  }

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
          {view === 'table' ? (
            <>Table includes <strong>all {normalized.nodes.length}</strong> normalized entities</>
          ) : (
            <>Showing <strong>{visibleNodes.length}</strong> of {normalized.nodes.length} normalized entities</>
          )}
        </span>
        <span>{pluralize(normalized.edges.length, 'normalized relationship', 'normalized relationships')}</span>
      </div>

      {explanationResource.status === 'success'
        && !explanationResource.data?.graph
        && !ringResource.data && (
        <p className="graph-provenance">
          Case trigger metadata only: the score explanation returned no graph object. Load the device
          neighborhood for a wider, separately sourced traversal.
        </p>
      )}

      {ringResource.status === 'error' && (
        <div className="context-warning graph-context-warning" role="status">
          <span>Device traversal failed: {ringResource.error}</span>
          <button className="button secondary compact-button" type="button" onClick={ringResource.retry}>
            Retry Device Traversal
          </button>
        </div>
      )}

      {view === 'graph' ? (
        <>
          <div className="graph-canvas" tabIndex={0} aria-label="Scrollable investigation graph">
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
                  <g key={`${edge.from}-${edge.to}-${edge.label}-${index}`} aria-hidden="true">
                    <path d={edgePath(from, to)} className="g-edge" />
                    <text x={labelX} y={labelY} textAnchor="middle" className="g-edge-label">
                      {edge.label}
                    </text>
                  </g>
                )
              })}
              {visibleNodes.map(node => {
                const [x, y] = layout.positions[node.id]
                const radius = node.type === 'transaction' ? 20 : node.type === 'case' ? 18 : 16
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
                {formatNumber(hiddenCount)} {hiddenCount === 1 ? 'entity is' : 'entities are'} hidden to keep this
                view readable. {formatNumber(hiddenEdgeCount)} related{' '}
                {hiddenEdgeCount === 1 ? 'relationship is' : 'relationships are'} omitted.
              </p>
              <button className="button secondary" type="button" onClick={() => setShowAll(true)}>
                Show +{formatNumber(hiddenCount)} More
              </button>
            </div>
          )}
          {showAll && normalized.nodes.length > MAX_VISIBLE_NODES && (
            <button className="button text-button" type="button" onClick={() => setShowAll(false)}>
              Show Compact View
            </button>
          )}

          <div className="graph-legend-row">
            <div className="legend" aria-label="Graph legend">
              {typesPresent.map(type => (
                <span className="legend-item" key={type}>
                  <i className={`legend-swatch ${type}`} aria-hidden="true" />
                  {NODE_LABELS[type]}
                </span>
              ))}
            </div>
            {flaggedTxnId && (
              <button
                className="button secondary compact-button"
                type="button"
                disabled={ringResource.status === 'loading' || Boolean(ringResource.data)}
                onClick={() => {
                  if (ringResource.status === 'error') ringResource.retry()
                  else setLoadNeighborhood(true)
                }}
              >
                {ringResource.status === 'loading'
                  ? 'Loading Device Neighborhood…'
                  : ringResource.data
                    ? 'Neighborhood Loaded'
                    : 'Load Device Neighborhood'}
              </button>
            )}
          </div>

          {ringResource.data && (
            <p className="graph-provenance">
              Device traversal ±{formatNumber(45)} days: {pluralize(ringCards.length, 'card')} returned,{' '}
              {pluralize(ringResource.data.n_txns, 'transaction')}.{' '}
              {explanationResource.status === 'error'
                ? 'The score explanation was unavailable; this graph uses case metadata plus the device traversal.'
                : 'The explanation response and traversal may expose different node counts.'}
            </p>
          )}
        </>
      ) : (
        <GraphTable normalized={normalized} caseId={caseId} visibleIds={visibleIds} />
      )}
    </section>
  )
}
