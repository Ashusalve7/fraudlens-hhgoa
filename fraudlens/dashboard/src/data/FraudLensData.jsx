import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import { fetchCase, fetchCases, fetchExplain, fetchRing, fetchStats } from '../api.js'

const DataContext = createContext(null)
const resourceCache = new Map()
const inFlightRequests = new Map()

async function requestResource(key, loader, force = false) {
  if (!force && resourceCache.has(key)) {
    return resourceCache.get(key)
  }
  if (inFlightRequests.has(key)) {
    return inFlightRequests.get(key)
  }
  if (force) resourceCache.delete(key)

  const request = Promise.resolve()
    .then(loader)
    .then(data => {
      resourceCache.set(key, data)
      inFlightRequests.delete(key)
      return data
    })
    .catch(error => {
      inFlightRequests.delete(key)
      throw error
    })

  inFlightRequests.set(key, request)
  return request
}

function cachedState(key) {
  if (!resourceCache.has(key)) {
    return { status: 'loading', data: null, error: null }
  }
  return { status: 'success', data: resourceCache.get(key), error: null }
}

function errorMessage(error) {
  return error instanceof Error ? error.message : 'The request could not be completed.'
}

export function FraudLensDataProvider({ children }) {
  const mounted = useRef(false)
  const [casesState, setCasesState] = useState(() => cachedState('cases'))
  const [statsState, setStatsState] = useState(() => cachedState('stats'))

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])

  const loadCases = useCallback(async (force = false) => {
    if (mounted.current) {
      setCasesState(force
        ? { status: 'loading', data: null, error: null }
        : cachedState('cases'))
    }

    try {
      const data = await requestResource('cases', fetchCases, force)
      if (mounted.current) setCasesState({ status: 'success', data, error: null })
      return data
    } catch (error) {
      if (mounted.current) {
        setCasesState({ status: 'error', data: null, error: errorMessage(error) })
      }
      throw error
    }
  }, [])

  const loadStats = useCallback(async (force = false) => {
    if (mounted.current) {
      setStatsState(force
        ? { status: 'loading', data: null, error: null }
        : cachedState('stats'))
    }

    try {
      const data = await requestResource('stats', fetchStats, force)
      if (mounted.current) setStatsState({ status: 'success', data, error: null })
      return data
    } catch (error) {
      if (mounted.current) {
        setStatsState({ status: 'error', data: null, error: errorMessage(error) })
      }
      throw error
    }
  }, [])

  useEffect(() => {
    loadCases().catch(() => {})
    loadStats().catch(() => {})
  }, [loadCases, loadStats])

  const retryCases = useCallback(() => {
    loadCases(true).catch(() => {})
  }, [loadCases])

  const retryStats = useCallback(() => {
    loadStats(true).catch(() => {})
  }, [loadStats])

  const value = useMemo(() => ({
    casesResource: { ...casesState, retry: retryCases },
    statsResource: { ...statsState, retry: retryStats },
  }), [casesState, statsState, retryCases, retryStats])

  return <DataContext.Provider value={value}>{children}</DataContext.Provider>
}

function useCaseResource(caseId, loaderFactory, namespace) {
  const dataContext = useContext(DataContext)
  if (!dataContext) {
    throw new Error('FraudLens data hooks must be used inside FraudLensDataProvider')
  }

  const key = `${namespace}:${caseId}`
  const loader = useCallback(() => loaderFactory(caseId), [caseId, loaderFactory])
  const [attempt, setAttempt] = useState(0)
  const [state, setState] = useState(() => (caseId ? cachedState(key) : {
    status: 'idle',
    data: null,
    error: null,
  }))

  useEffect(() => {
    let active = true
    if (!caseId) {
      setState({ status: 'idle', data: null, error: null })
      return () => {
        active = false
      }
    }

    const force = attempt > 0
    const cached = force ? null : resourceCache.get(key)

    if (cached !== undefined) {
      setState({ status: 'success', data: cached, error: null })
      return () => {
        active = false
      }
    }

    setState({ status: 'loading', data: null, error: null })
    requestResource(key, loader, force).then(
      data => {
        if (active) setState({ status: 'success', data, error: null })
      },
      error => {
        if (active) setState({ status: 'error', data: null, error: errorMessage(error) })
      },
    )

    return () => {
      active = false
    }
  }, [attempt, key, loader])

  const retry = useCallback(() => setAttempt(current => current + 1), [])
  return useMemo(() => ({ ...state, retry }), [state, retry])
}

export function useCaseDetail(caseId) {
  return useCaseResource(caseId, fetchCase, 'case')
}

export function useCaseExplanation(caseId) {
  return useCaseResource(caseId, fetchExplain, 'explanation')
}

export function useDeviceNeighborhood(txnId, windowDays = 45, enabled = true) {
  const dataContext = useContext(DataContext)
  if (!dataContext) {
    throw new Error('FraudLens data hooks must be used inside FraudLensDataProvider')
  }

  const key = `ring:${txnId}:${windowDays}`
  const loader = useCallback(
    () => fetchRing(txnId, windowDays),
    [txnId, windowDays],
  )
  const [attempt, setAttempt] = useState(0)
  const [state, setState] = useState(() => (txnId && enabled ? cachedState(key) : {
    status: 'idle',
    data: null,
    error: null,
  }))

  useEffect(() => {
    let active = true
    if (!enabled || !txnId) {
      setState({ status: 'idle', data: null, error: null })
      return () => {
        active = false
      }
    }

    const force = attempt > 0
    const cached = force ? null : resourceCache.get(key)
    if (cached !== undefined) {
      setState({ status: 'success', data: cached, error: null })
      return () => {
        active = false
      }
    }

    setState({ status: 'loading', data: null, error: null })
    requestResource(key, loader, force).then(
      data => {
        if (active) setState({ status: 'success', data, error: null })
      },
      error => {
        if (active) setState({ status: 'error', data: null, error: errorMessage(error) })
      },
    )

    return () => {
      active = false
    }
  }, [attempt, enabled, key, loader, txnId])

  const retry = useCallback(() => setAttempt(current => current + 1), [])
  return useMemo(() => ({ ...state, retry }), [state, retry])
}

export function useFraudLensData() {
  const context = useContext(DataContext)
  if (!context) {
    throw new Error('useFraudLensData must be used inside FraudLensDataProvider')
  }
  return context
}
