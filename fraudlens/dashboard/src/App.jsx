import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import {
  Link,
  Navigate,
  NavLink,
  Route,
  Routes,
  useLocation,
} from 'react-router-dom'
import {
  FraudLensDataProvider,
  useFraudLensData,
} from './data/FraudLensData.jsx'
import { formatNumber } from './lib/format.js'
import CasePage from './pages/CasePage.jsx'
import CasesPage from './pages/CasesPage.jsx'

const AnalyticsView = lazy(() => import('./components/AnalyticsView.jsx'))

function routeName(pathname) {
  if (pathname.startsWith('/cases/')) return 'Case investigation'
  if (pathname === '/analytics') return 'Case-pack analytics'
  if (pathname === '/cases') return 'Investigation queue'
  return 'Page not found'
}

function RouteFocus() {
  const location = useLocation()
  const routeLabel = routeName(location.pathname)

  useEffect(() => {
    document.title = `${routeLabel} · FraudLens`
    const frame = window.requestAnimationFrame(() => {
      document.getElementById('main-content')?.focus()
    })
    return () => window.cancelAnimationFrame(frame)
  }, [routeLabel, location.pathname])

  return (
    <p className="sr-only" aria-live="polite" aria-atomic="true">
      {routeLabel} loaded
    </p>
  )
}

function RouteLoading() {
  return (
    <main id="main-content" className="route-state" tabIndex="-1">
      <span className="loading-mark" aria-hidden="true" />
      <h1>Loading analytics…</h1>
      <p>Chart code is loading only when this route is opened.</p>
    </main>
  )
}

function NotFound() {
  return (
    <main id="main-content" className="route-state" tabIndex="-1">
      <p className="eyebrow">404</p>
      <h1>Workspace view not found</h1>
      <p>The requested route is not part of the FraudLens dashboard.</p>
      <Link className="button primary" to="/cases">Return to Investigations</Link>
    </main>
  )
}

function validCount(value) {
  const number = Number(value)
  return Number.isFinite(number) ? formatNumber(number, { compact: true }) : null
}

function WorkspaceShell() {
  const { casesResource, statsResource } = useFraudLensData()
  const location = useLocation()
  const [navOpen, setNavOpen] = useState(false)
  const menuButtonRef = useRef(null)
  const cases = Array.isArray(casesResource.data) ? casesResource.data : []
  const transactions = validCount(statsResource.data?.counts?.Transaction)
  const agentCases = validCount(statsResource.data?.counts?.AgentCase)

  useEffect(() => {
    setNavOpen(false)
  }, [location.pathname])

  useEffect(() => {
    if (!navOpen) return undefined
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const handleKeyDown = event => {
      if (event.key === 'Escape') {
        setNavOpen(false)
        window.requestAnimationFrame(() => menuButtonRef.current?.focus())
      }
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.body.style.overflow = previousOverflow
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [navOpen])

  const caseStatus = casesResource.status === 'loading'
    ? 'Loading case records…'
    : casesResource.status === 'error'
      ? 'Case API unavailable'
      : `${formatNumber(cases.length)} case records returned`
  const graphStatus = statsResource.status === 'loading'
    ? 'Loading snapshot…'
    : statsResource.status === 'error'
      ? 'Snapshot unavailable'
      : `${statsResource.data?.graph || 'Graph'} snapshot returned`

  return (
    <>
      <a className="skip-link" href="#main-content">Skip to Main Content</a>
      <div className={`shell${navOpen ? ' nav-open' : ''}`}>
        {navOpen && (
          <button
            className="sidebar-scrim"
            type="button"
            aria-label="Close navigation"
            onClick={() => {
              setNavOpen(false)
              window.requestAnimationFrame(() => menuButtonRef.current?.focus())
            }}
          />
        )}

        <header className="mobile-header">
          <Link to="/cases" className="mobile-brand" onClick={() => setNavOpen(false)}>
            <span className="brand-mark" aria-hidden="true">FL</span>
            <span><strong>FraudLens</strong><small>Analyst workspace</small></span>
          </Link>
          <button
            ref={menuButtonRef}
            className="button secondary menu-button"
            type="button"
            aria-controls="primary-navigation"
            aria-expanded={navOpen}
            onClick={() => setNavOpen(current => !current)}
          >
            {navOpen ? 'Close Menu' : 'Open Menu'}
          </button>
        </header>

        <aside id="primary-navigation" className="sidebar" aria-label="FraudLens sidebar">
          <Link className="brand" to="/cases" onClick={() => setNavOpen(false)}>
            <span className="brand-mark" aria-hidden="true">FL</span>
            <span>
              <strong className="brand-name">FraudLens</strong>
              <span className="brand-sub">Fraud operations</span>
            </span>
          </Link>

          <nav className="primary-nav" aria-label="Primary workspace">
            <p className="nav-section">Workspace</p>
            <NavLink
              to="/cases"
              className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}
            >
              <span className="nav-marker" aria-hidden="true" />
              Investigations
              <span className="nav-count">
                {casesResource.status === 'success' ? formatNumber(cases.length) : '—'}
              </span>
            </NavLink>
            <NavLink
              to="/analytics"
              className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}
            >
              <span className="nav-marker" aria-hidden="true" />
              Case-Pack Analytics
            </NavLink>
          </nav>

          <section className="sidebar-status" aria-labelledby="data-status-title">
            <div className="sidebar-section-title">
              <h2 id="data-status-title">Data Status</h2>
              <span className={`status-indicator ${casesResource.status}`} aria-hidden="true" />
            </div>
            <p className="status-primary">{caseStatus}</p>
            <dl>
              <div>
                <dt>Graph source</dt>
                <dd>{graphStatus}</dd>
              </div>
              <div>
                <dt>Transactions</dt>
                <dd>{transactions || 'Unavailable'}</dd>
              </div>
              <div>
                <dt>Agent cases</dt>
                <dd>{agentCases || 'Unavailable'}</dd>
              </div>
            </dl>
            {(casesResource.status === 'error' || statsResource.status === 'error') && (
              <div className="sidebar-retries">
                {casesResource.status === 'error' && (
                  <button className="sidebar-retry" type="button" onClick={casesResource.retry}>
                    Retry Case API
                  </button>
                )}
                {statsResource.status === 'error' && (
                  <button className="sidebar-retry" type="button" onClick={statsResource.retry}>
                    Retry Graph Snapshot
                  </button>
                )}
              </div>
            )}
          </section>

          <p className="sidebar-footnote">
            Read-only decision support. Recommended actions are not executed here.
          </p>
        </aside>

        <div className="content">
          <RouteFocus />
          <Routes>
            <Route path="/" element={<Navigate to="/cases" replace />} />
            <Route path="/cases" element={<CasesPage />} />
            <Route path="/cases/:caseId" element={<CasePage />} />
            <Route
              path="/analytics"
              element={(
                <Suspense fallback={<RouteLoading />}>
                  <AnalyticsView />
                </Suspense>
              )}
            />
            <Route path="*" element={<NotFound />} />
          </Routes>
        </div>
      </div>
    </>
  )
}

export default function App() {
  return (
    <FraudLensDataProvider>
      <WorkspaceShell />
    </FraudLensDataProvider>
  )
}
