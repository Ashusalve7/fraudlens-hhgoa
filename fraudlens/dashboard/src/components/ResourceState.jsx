export default function ResourceState({
  status = 'loading',
  title,
  message,
  actionLabel,
  onAction,
  compact = false,
  children,
}) {
  if (status === 'loading') {
    return (
      <div
        className={`resource-state${compact ? ' compact' : ''}`}
        role="status"
        aria-live="polite"
        aria-busy="true"
      >
        <span className="loading-mark" aria-hidden="true" />
        <div>
          <strong>{title || 'Loading…'}</strong>
          {message && <p>{message}</p>}
        </div>
      </div>
    )
  }

  if (status === 'error') {
    return (
      <div className={`resource-state error${compact ? ' compact' : ''}`} role="alert">
        <div>
          <strong>{title || 'Unable to load this view'}</strong>
          {message && <p>{message}</p>}
        </div>
        {actionLabel && onAction && (
          <button className="button secondary" type="button" onClick={onAction}>
            {actionLabel}
          </button>
        )}
      </div>
    )
  }

  return (
    <div className={`resource-state empty${compact ? ' compact' : ''}`}>
      <div>
        <strong>{title || 'No data available'}</strong>
        {message && <p>{message}</p>}
        {children}
      </div>
      {actionLabel && onAction && (
        <button className="button secondary" type="button" onClick={onAction}>
          {actionLabel}
        </button>
      )}
    </div>
  )
}
