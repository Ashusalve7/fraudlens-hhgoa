const integerFormatter = new Intl.NumberFormat(undefined, {
  maximumFractionDigits: 0,
})

const compactIntegerFormatter = new Intl.NumberFormat(undefined, {
  notation: 'compact',
  maximumFractionDigits: 1,
})

const currencyFormatter = new Intl.NumberFormat(undefined, {
  style: 'currency',
  currency: 'USD',
  currencyDisplay: 'narrowSymbol',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

const compactCurrencyFormatter = new Intl.NumberFormat(undefined, {
  style: 'currency',
  currency: 'USD',
  currencyDisplay: 'narrowSymbol',
  notation: 'compact',
  maximumFractionDigits: 1,
})

const decimalFormatter = new Intl.NumberFormat(undefined, {
  maximumFractionDigits: 2,
})

const percentFormatter = new Intl.NumberFormat(undefined, {
  style: 'percent',
  maximumFractionDigits: 4,
})

const shortDateFormatter = new Intl.DateTimeFormat(undefined, {
  dateStyle: 'medium',
})

const dateTimeFormatter = new Intl.DateTimeFormat(undefined, {
  dateStyle: 'medium',
  timeStyle: 'short',
})

export function formatNumber(value, options = {}) {
  const number = Number(value)
  if (!Number.isFinite(number)) return '—'
  if (options.compact) return compactIntegerFormatter.format(number)
  return integerFormatter.format(number)
}

export function formatCurrency(value, options = {}) {
  const number = Number(value)
  if (!Number.isFinite(number)) return '—'
  return (options.compact ? compactCurrencyFormatter : currencyFormatter).format(number)
}

export function formatDecimal(value, digits = 2) {
  const number = Number(value)
  if (!Number.isFinite(number)) return '—'
  if (digits === 2) return decimalFormatter.format(number)
  return new Intl.NumberFormat(undefined, {
    minimumFractionDigits: 0,
    maximumFractionDigits: digits,
  }).format(number)
}

export function formatPercent(value) {
  const number = Number(value)
  return Number.isFinite(number) ? percentFormatter.format(number) : '—'
}

export function parseLocalDate(value) {
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value
  if (typeof value !== 'string' || !value.trim()) return null

  const normalized = value.trim()
  const dateOnly = normalized.match(/^(\d{4})-(\d{2})-(\d{2})$/)
  if (dateOnly) {
    const [, year, month, day] = dateOnly
    return new Date(Number(year), Number(month) - 1, Number(day))
  }

  const parsed = new Date(normalized.includes('T') ? normalized : normalized.replace(' ', 'T'))
  return Number.isNaN(parsed.getTime()) ? null : parsed
}

export function formatDate(value, fallback = 'Not supplied') {
  const date = parseLocalDate(value)
  return date ? shortDateFormatter.format(date) : fallback
}

export function formatDateTime(value, fallback = 'Not supplied') {
  const date = parseLocalDate(value)
  return date ? dateTimeFormatter.format(date) : fallback
}

export function formatLatency(value) {
  const number = Number(value)
  return Number.isFinite(number) ? `${decimalFormatter.format(number)} s` : '—'
}

export function titleCaseToken(value) {
  if (value === null || value === undefined) return 'Not supplied'
  return String(value)
    .replace(/[_-]+/g, ' ')
    .replace(/\b\w/g, character => character.toUpperCase())
}

export function pluralize(count, singular, plural = `${singular}s`) {
  return `${formatNumber(count)} ${Number(count) === 1 ? singular : plural}`
}
