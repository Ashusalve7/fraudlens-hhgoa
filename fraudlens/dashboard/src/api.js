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

  try {
    return await response.json()
  } catch {
    throw new Error(`${unavailableMessage}. The API returned an unreadable response.`)
  }
}

export function fetchCases() {
  return requestJson('/api/cases', 'The case queue is unavailable')
}

export function fetchCase(id) {
  return requestJson(`/api/cases/${encodeURIComponent(id)}`, 'The case detail is unavailable')
}

export function fetchStats() {
  return requestJson('/api/graph/stats', 'Graph context is unavailable')
}

export function fetchRing(txnId) {
  return requestJson(
    `/api/graph/ring/${encodeURIComponent(txnId)}`,
    'The device neighborhood is unavailable',
  )
}

export function fetchExplain(caseId) {
  return requestJson(
    `/api/explain/${encodeURIComponent(caseId)}`,
    'The score explanation is unavailable',
  )
}
