import { useMemo, useState } from 'react'
import { formatCurrency, formatDate } from '../lib/format.js'
import ResourceState from './ResourceState.jsx'

function buildSarText(answer) {
  const sar = answer?.sar || {}
  const dates = Array.isArray(sar.activity_dates) ? sar.activity_dates : []
  const start = dates[0] ? formatDate(dates[0], dates[0]) : 'Not supplied'
  const end = dates.length > 1 ? formatDate(dates.at(-1), dates.at(-1)) : null
  const subjects = Array.isArray(sar.subjects) && sar.subjects.length > 0
    ? sar.subjects.join(', ')
    : 'Not supplied'

  return [
    `SAR Draft — ${answer.case_id}`,
    'DRAFT ONLY — filing status is not confirmed by the API',
    '',
    `Subjects: ${subjects}`,
    `Total amount: ${formatCurrency(sar.total_amount_usd)}`,
    `Activity period: ${start}${end ? ` to ${end}` : ''}`,
    '',
    `Assessment reason: ${sar.reason || 'Not supplied'}`,
    '',
    'Draft narrative',
    sar.narrative || 'No narrative was supplied.',
  ].join('\n')
}

async function copyText(text) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text)
    return
  }

  const textarea = document.createElement('textarea')
  textarea.value = text
  textarea.setAttribute('readonly', '')
  textarea.style.position = 'fixed'
  textarea.style.opacity = '0'
  document.body.appendChild(textarea)
  textarea.select()
  const copied = document.execCommand('copy')
  textarea.remove()
  if (!copied) throw new Error('Clipboard access was not available.')
}

export default function SarDraft({ answer }) {
  const [copyStatus, setCopyStatus] = useState('')
  const sar = answer?.sar || {}
  const hasSarRecord = Boolean(sar.file || sar.narrative || sar.reason)
  const text = useMemo(() => buildSarText(answer), [answer])
  const dates = Array.isArray(sar.activity_dates) ? sar.activity_dates : []

  async function handleCopy() {
    try {
      await copyText(text)
      setCopyStatus('SAR Draft copied to the clipboard.')
    } catch {
      setCopyStatus('The draft could not be copied. Use Export Draft instead.')
    }
  }

  function handleExport() {
    const blob = new Blob([text], { type: 'text/plain;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${String(answer.case_id || 'case').replace(/[^a-z0-9_-]/gi, '-')}-sar-draft.txt`
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(url)
    setCopyStatus('SAR Draft export prepared.')
  }

  return (
    <section className="panel sar-panel" aria-labelledby="sar-title">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Regulatory Workspace</p>
          <h2 id="sar-title">SAR Draft</h2>
        </div>
        <span className="draft-chip">Draft · filing unconfirmed</span>
      </div>

      {!hasSarRecord ? (
        <ResourceState
          compact
          status="empty"
          title="No SAR assessment returned"
          message="This case response contains no SAR record or narrative."
        />
      ) : !sar.narrative ? (
        <ResourceState
          compact
          status="empty"
          title="No draft narrative available"
          message="The assessment reason is present, but there is no narrative to copy or export."
        />
      ) : (
        <>
          <p className="simulation-note">
            This is a case-pack draft, not confirmation that a report was filed with any authority.
          </p>
          <div className="draft-toolbar">
            <div>
              <strong>Draft artifact</strong>
              <span>Review before any external use.</span>
            </div>
            <div className="button-row">
              <button className="button secondary" type="button" onClick={handleCopy}>
                Copy Draft
              </button>
              <button className="button secondary" type="button" onClick={handleExport}>
                Export Draft (.txt)
              </button>
            </div>
          </div>
          <p className="sar-reason"><strong>Assessment reason:</strong> {sar.reason || 'Not supplied'}</p>
          <blockquote>{sar.narrative}</blockquote>
          <dl className="sar-facts">
            <div>
              <dt>Subjects</dt>
              <dd>{sar.subjects?.length ? sar.subjects.join(', ') : 'Not supplied'}</dd>
            </div>
            <div>
              <dt>Total amount</dt>
              <dd>{formatCurrency(sar.total_amount_usd)}</dd>
            </div>
            <div>
              <dt>Activity period</dt>
              <dd>
                {dates.length
                  ? `${formatDate(dates[0])}–${formatDate(dates.at(-1))}`
                  : 'Not supplied'}
              </dd>
            </div>
          </dl>
          <p className="sr-status" role="status" aria-live="polite">{copyStatus}</p>
        </>
      )}
    </section>
  )
}
