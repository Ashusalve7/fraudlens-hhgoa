export function getRiskBand(probability) {
  const value = Number(probability)
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
  return getFinalActions(nextBestActions).filter(action => action?.route && action.route !== 'auto')
}

export function actionKey(action) {
  return `${action?.action || 'UNKNOWN_ACTION'}::${action?.route || 'UNKNOWN_ROUTE'}`
}
