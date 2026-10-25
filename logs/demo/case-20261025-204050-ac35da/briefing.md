# Intelligence briefing — case case-20261025-204050-ac35da

**Question:** As of 25 January 2027, how exposed are Midgard and Tolan to the end of the Orvan corridor agreement? Give a low and high range for wheat and maize imports.  
**As of:** 2027-01-25  
**Status:** INCOMPLETE (runs completed: 1; findings from the run 1 rulings)

> This briefing is **INCOMPLETE**: Odin judged the evidence insufficient after 1 run(s). See *Investigation runs* and *Missing data*.

## Executive summary

As of 25 January 2027, the expiration of the Orvan Grain Corridor Agreement on 10 September 2026 has resulted in significant trade exposure for Midgard and Tolan. Midgard wheat imports from Orvan fell by USD 156.5M to USD 216.2M YoY in the months following expiration. Midgard's maize imports saw a delayed impact due to contractual terms, eventually dropping by over USD 100M YoY in late Q4. Tolan's wheat imports were similarly impacted, showing a deficit of USD 69.6M to USD 96.0M. In all cases, while alternative shipments from Vanir and rail routes provided some relief, they remained small in scale compared to the lost maritime volumes from Orvan and were often more expensive to handle.

## Event verification

**Status: established** — Official government notices and reliable trade sources confirm that the Corridor Agreement, signed on 10 September 2025 for a one-year period, expired on 10 September 2026 without a replacement agreement.

- ORV-0002 P2: “The agreement was signed on 10 September 2025 and ran for one year. It covered wheat and maize shipped by sea from Orvan Grain Port.” [ORV-0002 P2, 2026-06-15]
- ORV-0006 P3: “Midgard buyers had expected the corridor agreement to be renewed. It expired on 10 September without a replacement.” [ORV-0006 P3, 2026-10-08]

## Established findings

- **T1-1** (inference) Midgard wheat imports from Orvan experienced severe declines post-corridor expiration, demonstrating high trade exposure. [ORV-0009#R3, 2027-01-19] [ORV-0009#R9, 2027-01-19]
  - *Odin:* Official trade data from the Realm Trade Ministry confirms a significant year-over-year reduction in wheat import value from Orvan to Midgard following the corridor's expiration on 10 September 2026. The high bound includes the full transition month of September, while the low bound covers the subsequent fully disrupted months.
- **T1-2** (inference) Midgard maize imports dropped substantially following the expiration of delayed delivery terms, leading to high exposure. [ORV-0030#R5, 2027-01-21] [ORV-0030#R11, 2027-01-21]
  - *Odin:* Midgard maize imports showed a delayed contraction due to existing delivery terms in October, but trade data for November and December 2026 confirms a steep decline (over USD 100M YoY) once those terms expired. The proponent's range is supported by CALC-c4d8aa36b4090272 and CALC-8b68f9523d386676.
- **T1-3** (inference) Tolan wheat imports suffered immediate and persistent losses following the end of the Orvan corridor agreement. [ORV-0046#R3, 2027-01-20] [ORV-0046#R9, 2027-01-20]
  - *Odin:* Trade notes from Harbour Review demonstrate immediate and substantial YoY losses in wheat imports for Tolan. While alternative supplies exist, they were explicitly identified as insufficient to bridge the gap (ORV-0046/P14).
- **L1-4** (fact) Tolan's maize exposure cannot be quantified directly from official trade tables due to absent trade records, representing a major data gap. [ORV-0024 P3, 2026-09-12]
  - *Odin:* No specific trade table for Tolan maize imports (comparable to ORV-0009 or ORV-0030) was provided in the evidence, preventing a quantitative calculation for this specific pair.

## Contested findings

- **L1-1** (inference) Midgard's post-expiration wheat import decline from Orvan was limited to a net YoY reduction of USD 156.5M to USD 216.2M across the late 2026 months, buffered partly by alternative Vanir exports. [ORV-0009#R3, 2027-01-19] [ORV-0024 P6, 2026-09-12]
  - *Odin:* The numerical range for the bilateral drop is valid, but the claim that Vanir exports significantly 'buffered' the loss is undermined by evidence stating Vanir's supply is 'small' (ORV-0024/P6) and 'more expensive to handle' (ORV-0022/P5).

## Conceded findings

- **L1-2** (inference) Midgard's maize import exposure following the Orvan corridor expiration was delayed and limited to between USD 126.4M and USD 128.7M in YoY import reductions due to delayed delivery terms. — revised after partial concession: Midgard's maize import exposure following the Orvan corridor expiration was delayed into October 2026 by existing delivery terms, after which imports contracted sharply in November and December 2026. [ORV-0030 P14, 2027-01-21] [ORV-0030#R4, 2027-01-21]
  - *Odin:* The proponent conceded that the buffer provided by delayed delivery terms was only temporary and that imports contracted sharply in late Q4 2026.
- **L1-3** (fact) Tolan wheat imports saw moderate post-expiration declines from Orvan, but exposure is mitigated by alternative shipments from Vanir. — revised after partial concession: Tolan wheat imports saw post-expiration declines from Orvan, and while alternative shipments from Vanir provided partial substitution, they were insufficient to fully offset the import gap. [ORV-0035 P4, 2027-01-14] [ORV-0046#R3, 2027-01-20]
  - *Odin:* The proponent conceded that Vanir shipments were insufficient to fully offset the import gap created by the corridor expiration.

## Rejected claims

_None._

## Exposure

Separate ranges from each side and from Odin's ruling; Odin's range is not an average.

| Country | Sector | Metric (unit, period, denominator) | Thor (high case) | Loki (limited case) | Odin (ruling) | Notes |
|---|---|---|---|---|---|---|
| Midgard | maize | YoY import value loss (USD M, Oct-Dec 2026 vs Oct-Dec 2025, per None) | 105.7 – 126.4 USD M | unavailable (estimate removed by code: numbers not reproducible from calc records) | 105.7 – 126.4 USD M | Thor T1-2: established |
| Midgard | wheat | YoY import value loss (USD M, Sept-Dec 2026 vs Sept-Dec 2025, per None) | 156.5 – 216.2 USD M | unavailable (estimate removed by code: numbers not reproducible from calc records) | 156.5 – 216.2 USD M | Thor T1-1: established |
| Tolan | maize | — | unavailable (no estimate submitted by thor for this pair) | unavailable (no estimate submitted by loki for this pair) | unavailable (insufficient evidence: Trade table detailing Orvan-to-Tolan maize exports for 2025 and 2026.) |  |
| Tolan | wheat | YoY import value loss (USD M, Sept-Dec 2026 vs Sept-Dec 2025, per None) | 69.6 – 96.0 USD M | unavailable (no estimate submitted by loki for this pair) | 69.6 – 96.0 USD M | Thor T1-3: established |

- **Thor — Midgard/maize:** YoY import value loss: Year-over-year reduction in maize import value from Orvan post-expiration. Unit USD M, period Post-expiration 2026 vs 2025, denominator N/A. Calculations: CALC-c4d8aa36b4090272, CALC-8b68f9523d386676 (rows ORV-0030#R10, ORV-0030#R11, ORV-0030#R12, ORV-0030#R4, ORV-0030#R5, ORV-0030#R6). Confidence: high. Missing: Exact baseline substitution levels..
- **Odin — Midgard/maize:** YoY import value loss: Year-over-year reduction in maize import value from Orvan post-expiration. Unit USD M, period Oct-Dec 2026 vs Oct-Dec 2025, denominator None. Calculations: CALC-c4d8aa36b4090272, CALC-8b68f9523d386676 (rows ORV-0030#R10, ORV-0030#R11, ORV-0030#R12, ORV-0030#R4, ORV-0030#R5, ORV-0030#R6). Confidence: medium.
- **Thor — Midgard/wheat:** YoY import value loss: Year-over-year reduction in wheat import value from Orvan following corridor expiration. Unit USD M, period Post-expiration 2026 vs 2025, denominator N/A. Calculations: CALC-cb98e8e7d6f3bbe6, CALC-2471c1be02c2601c (rows ORV-0009#R10, ORV-0009#R11, ORV-0009#R12, ORV-0009#R3, ORV-0009#R4, ORV-0009#R5, ORV-0009#R6, ORV-0009#R9). Confidence: high. Missing: Alternative rail imports not fully captured..
- **Odin — Midgard/wheat:** YoY import value loss: Year-over-year reduction in wheat import value from Orvan following the corridor expiration on 10 Sept 2026. Unit USD M, period Sept-Dec 2026 vs Sept-Dec 2025, denominator None. Calculations: CALC-cb98e8e7d6f3bbe6, CALC-2471c1be02c2601c (rows ORV-0009#R10, ORV-0009#R11, ORV-0009#R12, ORV-0009#R3, ORV-0009#R4, ORV-0009#R5, ORV-0009#R6, ORV-0009#R9). Confidence: high.
- **Thor — Tolan/wheat:** YoY import value loss: Year-over-year reduction in wheat import value from Orvan. Unit USD M, period Post-expiration 2026 vs 2025, denominator N/A. Calculations: CALC-d0e20968679cf6e7, CALC-c1d6da086b7f9f04 (rows ORV-0046#R10, ORV-0046#R11, ORV-0046#R12, ORV-0046#R3, ORV-0046#R4, ORV-0046#R5, ORV-0046#R6, ORV-0046#R9). Confidence: high. Missing: Exact Vanir offset numbers not fully itemized..
- **Odin — Tolan/wheat:** YoY import value loss: Year-over-year reduction in wheat import value from Orvan following the corridor expiration. Unit USD M, period Sept-Dec 2026 vs Sept-Dec 2025, denominator None. Calculations: CALC-d0e20968679cf6e7, CALC-c1d6da086b7f9f04 (rows ORV-0046#R10, ORV-0046#R11, ORV-0046#R12, ORV-0046#R3, ORV-0046#R4, ORV-0046#R5, ORV-0046#R6, ORV-0046#R9). Confidence: high.

## Assumptions and uncertainty

- T1-1 (inference): Trade reduction directly reflects corridor agreement expiration.
- T1-2 (inference): Delayed deliveries postponed post-expiration impact until late Q4 2026.
- T1-3 (inference): Tolan relies heavily on Orvan maritime wheat shipments.
- L1-1 (inference): Post-expiration disruption is evaluated based on year-over-year changes post-September 2026.
- L1-1 (inference): Vanir wheat exports partially offset losses.
- L1-2 (inference): Delayed delivery terms provided a buffer against immediate post-expiration supply drops in October 2026.
- L1-3 (fact): Vanir wheat shipments buffer Tolan's import gap.
- Thor Midgard/maize estimate: November-December drop demonstrates full effect after delayed contracts cleared.
- Odin Midgard/maize estimate: Low bound (Nov-Dec) reflects the period after delayed delivery terms expired; High bound (Oct-Dec) includes the initial impact month.
- Thor Midgard/wheat estimate: Corridor expiration drove the monthly YoY deficit.
- Odin Midgard/wheat estimate: Low bound excludes the transition month (September) to show full disruption impact; High bound includes the transition month.
- Thor Tolan/wheat estimate: Corridor expiration is primary driver of import fall.
- Odin Tolan/wheat estimate: Range reflects 3-month vs 4-month YoY deficit to account for the expiration timing.
- Uncertainty: Thor Midgard/maize: confidence high — Lower bound uses Nov-Dec post-expiration window; upper bound includes October transition.
- Uncertainty: Odin Midgard/maize: confidence medium — Exposure was obscured in October by contractual delivery lags but became severe in November and December.
- Uncertainty: Thor Midgard/wheat: confidence high — Range depends on whether September 2026 transition month is included.
- Uncertainty: Odin Midgard/wheat: confidence high — Calculations based on Ministry of Trade records show significant losses. While substitution exists, it is documented as small compared to the bilateral deficit.
- Uncertainty: Thor Tolan/wheat: confidence high — Depends on inclusion of September 2026 transition month.
- Uncertainty: Odin Tolan/wheat: confidence high — Tolan suffered immediate losses as evidenced by Harbour Review trade notes; Vanir substitution was confirmed to be insufficient to close the gap.

## Investigation runs

- **Run 1:** 7 claim(s) ruled (conceded 2, contested 1, established 4); Odin: insufficient. Sent back for: Monthly trade volume and value for Tolan maize imports from Orvan (2025-2026).. 
- **Run 2:** no rulings; Notes: run 2: Heimdall's targeted searches found no genuinely new relevant evidence (code check: no cited ref outside run 1-1 evidence and its duplicates); advocates and Odin were not re-run and the briefing (from the run 1 rulings) is labelled incomplete

## Next-quarter outlook

The outlook for Q1 2027 remains constrained. Without a renewal of the corridor agreement or a massive scale-up in alternative logistics (rail or Vanir supply), import volumes for wheat and maize are expected to remain at these depressed levels. High handling costs for substitute supplies will likely continue to pressure grain millers and industrial buyers in Midgard and Tolan.

Assumptions:
- No new maritime corridor agreement is reached in early 2027.
- Vanir supply remains stable but limited by current logistical capacity.
- Rail routes continue to operate at high capacity but cannot fully replace lost sea volumes.

## Missing data and evidence quality

- Odin judged the evidence insufficient: We lack specific quantitative trade data for Tolan's maize imports from Orvan, which prevents a full assessment of total exposure for both requested countries.
- Monthly trade volume and value for Tolan maize imports from Orvan (2025-2026). (why: Necessary to calculate the year-over-year deficit for maize following the corridor expiration.)
- Tolan/maize: Trade table detailing Orvan-to-Tolan maize exports for 2025 and 2026.
- Trade data from the Realm Trade Ministry (Tier 1) and Harbour Review (Tier 2) are consistent and provide a clear picture of bilateral declines.
- The absence of a specific trade table for Tolan maize is the primary data deficiency.

## Traps, corrections and failures

- run 2: Heimdall's targeted searches found no genuinely new relevant evidence (code check: no cited ref outside run 1-1 evidence and its duplicates); advocates and Odin were not re-run and the briefing (from the run 1 rulings) is labelled incomplete

## Sources

All sources are Runemark documents from the ingested evidence packs.

- ORV-0002 — Corridor Agreement: terms of the one-year grain arrangement — Realm Trade Ministry (tier 1), 2026-06-15 09:00
- ORV-0006 — Millers look beyond Orvan as wheat cargoes slip — Midgard Times (tier 2), 2026-10-08 08:45
- ORV-0009 — Trade note: Orvan to Midgard, wheat, July to December 2026 — Realm Trade Ministry (tier 1), 2027-01-19 09:20
- ORV-0024 — How the Orvan grain corridor worked, and why its ending matters — Harbour Review (tier 2), 2026-09-12 10:15
- ORV-0030 — Trade note: Orvan to Midgard, maize, July to December 2026 — Realm Trade Ministry (tier 1), 2027-01-21 09:35
- ORV-0035 — December loadings close a poor quarter at Orvan Grain Port — Cargo Weekly (tier 2), 2027-01-14 12:10
- ORV-0046 — Trade note: Orvan to Tolan, wheat, July to December 2026 — Harbour Review (tier 2), 2027-01-20 10:05
