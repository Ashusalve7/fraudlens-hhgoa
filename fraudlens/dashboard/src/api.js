async function requestJson(path, unavailableMessage) {
  let response
  try {
    response = await fetch(path, {
      headers: { Accept: 'application/json' },
    })
  } catch {
    throw new Error(`${unavailableMessage}. Check that the dashboard API is running.`)
  }

  if (!response.ok) {
    if (response.status === 404) throw new Error('The requested record was not found.')
    throw new Error(`${unavailableMessage} (HTTP ${response.status}).`)
  }

  let payload
  try {
    payload = await response.json()
  } catch {
    throw new Error(`${unavailableMessage}. The API returned an unreadable response.`)
  }
  if (payload?.available === false || payload?.status === 'unavailable') {
    throw new Error(payload.detail || `${unavailableMessage}. The service reported itself unavailable.`)
  }
  return payload
}

export async function fetchCases() {
  const data = await requestJson('/api/cases', 'The case queue is unavailable')
  if (!Array.isArray(data)) throw new Error('The case queue response was not a list.')
  return data
}

export async function fetchCase(id) {
  const data = await requestJson(`/api/cases/${encodeURIComponent(id)}`, 'The case detail is unavailable')
  if (!data?.case) throw new Error('The case detail response did not include a case record.')
  return data
}

export async function fetchStats() {
  const data = await requestJson('/api/graph/stats', 'Graph context is unavailable')
  if (!data || typeof data !== 'object' || Array.isArray(data)) {
    throw new Error('The graph snapshot response was incomplete.')
  }
  return data
}

export async function fetchRing(txnId, windowDays = 45) {
  const days = Number.isFinite(Number(windowDays))
    ? Math.max(1, Math.min(365, Math.trunc(Number(windowDays))))
    : 45
  const data = await requestJson(
    `/api/graph/ring/${encodeURIComponent(txnId)}?window_days=${days}`,
    'The device neighborhood is unavailable',
  )
  if (!data || !data.device || !Array.isArray(data.cards) || !Array.isArray(data.sample)) {
    throw new Error('The device neighborhood response was incomplete.')
  }
  return data
}

export async function fetchExplain(caseId) {
  const data = await requestJson(
    `/api/explain/${encodeURIComponent(caseId)}`,
    'The score explanation is unavailable',
  )
  const probability = data?.probability
  const hasProbability = probability !== null && probability !== undefined && probability !== ''
  if (!data || !Array.isArray(data.contributions) || !hasProbability || !Number.isFinite(Number(probability))) {
    throw new Error('The score explanation response was incomplete.')
  }
  return data
}
