import { formatPercent } from '../lib/format.js'

const severityColor = probability =>
  probability >= 0.85
    ? '#b42318'
    : probability >= 0.6
      ? '#9a6700'
      : probability >= 0.3
        ? '#8a5200'
        : '#087443'

export default function RiskGauge({ value, size = 62, stroke = 7 }) {
  const hasValue = value !== null && value !== undefined && value !== ''
  const numericValue = Number(value)
  const validValue = hasValue && Number.isFinite(numericValue) && numericValue >= 0 && numericValue <= 1
  const percentage = validValue
    ? Math.max(0, Math.min(1, numericValue))
    : 0
  const accessibleValue = validValue ? formatPercent(numericValue) : 'not scored'
  const radius = (size - stroke) / 2
  const circumference = 2 * Math.PI * radius
  const color = validValue ? severityColor(percentage) : '#596579'

  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      role="img"
      aria-label={`Estimated fraud likelihood: ${accessibleValue}`}
      className="risk-gauge"
    >
      <title>Estimated fraud likelihood: {accessibleValue}</title>
      <circle
        cx={size / 2}
        cy={size / 2}
        r={radius}
        fill="none"
        stroke="#e3e8ef"
        strokeWidth={stroke}
      />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={radius}
        fill="none"
        stroke={color}
        strokeWidth={stroke}
        strokeLinecap="round"
        strokeDasharray={`${circumference * percentage} ${circumference}`}
        transform={`rotate(-90 ${size / 2} ${size / 2})`}
      />
      <text
        x="50%"
        y="50%"
        dominantBaseline="central"
        textAnchor="middle"
        style={{
          fontSize: size * 0.27,
          fontWeight: 750,
          fill: color,
          fontVariantNumeric: 'tabular-nums',
        }}
      >
        {validValue
          ? new Intl.NumberFormat(undefined, { maximumFractionDigits: 0 }).format(percentage * 100)
          : '—'}
      </text>
    </svg>
  )
}
