# Independent benchmark review notes

This is the pre-regeneration human review of the 20 case triggers. It is a review aid, not a hidden label source. The final decision remains the structured output of the cutoff-aware runner plus deterministic policy.

| Case | Independent pre-cutoff assessment | Main caution |
|---|---|---|
| HHG-001 | Likely legitimate/uncertain; not defensible OOR | Region was established; do not import a broad in-person history as an episode. |
| HHG-002 | Suspicious CNP, pending verification | Customer denial is not a later simulated response. |
| HHG-003 | R7 is plausible but not proven | ProductCD is not a merchant identity; do not overstate monthly recurrence. |
| HHG-004 | Likely fraud; CNP from a New device | Exclude all post-`opened_at` rows; no SAR without threshold/connected basis. |
| HHG-005 | Uncertain; one New-device signal is insufficient | Generic device reuse is monitoring, not connected fraud. |
| HHG-006 | Likely compact New-device/proxy CNP fraud | Preserve the pre-cutoff burst; do not add future rows. |
| HHG-007 | ATO claim unsupported; likely uncertain | Ordinary card-present activity is not an ATO episode. |
| HHG-008 | R7 plausible but not proven | Similar amounts are not proof of a merchant/monthly cadence. |
| HHG-009 | Customer denial is credible; evidence mechanics are weak | Treat the report as initial denial only. |
| HHG-010 | High suspicion; do not auto-close on a low model score | New device, amount anomaly, and email anomaly require verification/escalation. |
| HHG-011 | R7/compact fraud remains ambiguous | Do not turn a large historical card into a broad episode without anomaly evidence. |
| HHG-012 | Likely legitimate/uncertain; OOR contradicted | Region had prior use. |
| HHG-013 | Moderate CNP/New-device suspicion, not proven | Generic device neighborhood is not a fraud ring. |
| HHG-014 | Strongest coordinated graph case; likely fraud | Use the distinctive profile, pre-cutoff window, and explicit corroboration; no invented dollar threshold. |
| HHG-015 | Uncertain; legitimate high-spend explanation exists | Do not hard-code a confirmation response. |
| HHG-016 | Customer denial supports fraud; independent anomaly evidence is weak | No SAR without threshold/connected basis. |
| HHG-017 | Suspicious repeated online activity, not proven card testing | Use verification before blocking absent denial/corroboration. |
| HHG-018 | R7 plausible but not proven | Frequent similar amounts are not automatically a monthly recurring charge. |
| HHG-019 | Legitimate/uncertain; auto-close is premature | Do not invent a simulated confirmation or action transition. |
| HHG-020 | Weak CNP/New-device signal; overconfident block risk | Verify before blocking. |

## Review rules

- Use only rows available at `opened_at`.
- A customer-report trigger is observed denial evidence; any later response is simulated.
- Shared device reuse alone is a monitoring lead, not connected-card fraud.
- A SAR requires a structured policy basis; a generic device neighborhood is insufficient.
- When the data cannot distinguish a legitimate explanation, retain uncertainty instead of forcing a balanced verdict.
