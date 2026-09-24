export default function Queue({ cases, selected, onSelect }) {
  return (
    <ul className="queue">
      {cases.map(c => (
        <li key={c.case_id}>
          <button
            className={c.case_id === selected ? 'case-item selected' : 'case-item'}
            onClick={() => onSelect(c.case_id)}
          >
            <span className="qrow1">
              <span className="cid">{c.case_id}</span>
              <span style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                {c.sar && <span className="sar-chip">SAR</span>}
                <span className={`verdict ${c.verdict}`}>{c.verdict}</span>
              </span>
            </span>
            <span className="qrow2">
              <span className="qpattern">{c.pattern.replace(/_/g, ' ')}</span>
              <span className="qprob">{Math.round(c.fraud_probability * 100)}%</span>
            </span>
          </button>
        </li>
      ))}
    </ul>
  )
}
