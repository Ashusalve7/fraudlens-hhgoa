export function getRiskBand(probability) {
  if (probability === null || probability === undefined || probability === '') {
    return { key: 'unknown', label: 'Not scored' }
  }
  const value = Number(probability)
  if (!Number.isFinite(value) || value < 0 || value > 1) {
    return { key: 'unknown', label: 'Not scored' }
  }
  if (value >= 0.85) return { key: 'critical', label: 'Critical' }
  if (value >= 0.6) return { key: 'high', label: 'High' }
  if (value >= 0.3) return { key: 'elevated', label: 'Elevated' }
  return { key: 'low', label: 'Lower' }
}

export function getVerdictLabel(verdict) {
  if (verdict === 'fraud') return 'Fraud'
  if (verdict === 'legitimate') return 'Legitimate'
  if (verdict === 'uncertain') return 'Uncertain'
  return 'Unresolved'
}

export function getStatusLabel(status) {
  if (!status) return 'Status not supplied'
  return String(status)
    .replace(/^closed_/, '')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, character => character.toUpperCase())
}

export function getFinalActions(nextBestActions) {
  return Array.isArray(nextBestActions?.final) ? nextBestActions.final : []
}

export function getManualActions(nextBestActions) {
  return getFinalActions(nextBestActions).filter(action => {
    const route = String(action?.route || '').trim().toLowerCase()
    return route && route !== 'auto'
  })
}

export function getApprovalState(answer) {
  const sources = [
    [answer?.approval?.status, 'Case response'],
    [answer?.approval?.decision, 'Case response'],
    [answer?.approval_state, 'Case response'],
    [answer?.next_best_actions?.approval_state, 'Action snapshot'],
  ]
  const match = sources.find(([candidate]) => (
    candidate !== null
    && candidate !== undefined
    && String(candidate).trim()
  ))
  if (!match) return null
  return {
    value: String(match[0]).trim(),
    source: match[1],
  }
}

export function actionKey(action) {
  return `${action?.action || 'UNKNOWN_ACTION'}::${action?.route || 'UNKNOWN_ROUTE'}`
}
