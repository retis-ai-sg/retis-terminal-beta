# Formulas, glossary, and experiment journal

[繁體中文](../zh-TW/appendix.md) · [简体中文](../zh-CN/appendix.md) · English · [Edition contents](README.md)

## Quick reference

| Term | Meaning in this book |
| --- | --- |
| Bar | One recorded interval, such as a day's close. Counts refer to rows available in the replay. |
| Spread | The weighted difference between the two inputs. |
| Hedge ratio | The weight in the spread. In some sizing modes the estimate also informs the number of reference units. |
| Z-score | How far the spread is from its rolling mean, measured in standard deviations. |
| Warm-up | Observations needed before a calculation has enough data to produce a value. |
| Leg | One stock or instrument in the pair, with its own price, quantity, and costs. |
| Gross notional | Sum of the absolute price × quantity × multiplier of both legs. |
| Drawdown | The drop from an earlier cumulative P&L peak to a later low. |
| Holdout | Later data set aside before you choose or tune the rule. |
| Lineage | The saved record of where the data came from and how it was mapped. |

## Formula sheet

- **Percentage change** = (new value − old value) ÷ old value × 100.
- **Fixed price spread** = primary price × primary multiplier − hedge ratio × reference price × reference multiplier.
- **Z-score** = (spread − mean of latest N spreads) ÷ their population standard deviation. The latest N include the current value.
- **Gross leg P&L** = (exit − entry) × signed quantity × multiplier. Add the legs.
- **Estimated net P&L** = gross P&L − costs you have identified. If starting from a report's net P&L, subtract only additional unmodeled costs. Treat funding or carry separately as recorded.
- **Gross entry notional** = sum of absolute entry price × quantity × multiplier for each leg. For the return percentage, use the exact denominator reported by the view.
- **Drawdown** at a timestamp = previous running P&L peak − current cumulative P&L. The maximum is the largest such drop.

## Experiment journal

Copy this table for each experiment. Fill in the first half before opening your holdout report.

| Record | Your notes |
| --- | --- |
| Question and pair order | Why might this gap narrow? Which leg is primary? |
| Rejection condition | What result or data issue would make you stop using this hypothesis? |
| Inputs | Source, exact field, interval, time zone, and coverage for each leg. |
| Rule | Spread basis, ratio method and value, hedge window, z-score period, in/out thresholds. |
| Sizing and costs | Mode, actual amounts, multiplier, fees, slippage and borrowing assumptions. |
| Formation / holdout | Requested and observed dates, confirmation they do not overlap, and what history informed your choices. |
| Saved results | Labels of the saved reports, observations, missing or warm-up rows, closed trades, total P&L, drawdown and any open position. |
| Automatic run, if used | Sample bounds, m, n, range of lengths, seed and snapshot. Note overlapping windows. |
| Paper observation | Date and time, quote timestamps, freshness, signal or skipped action, and final position. |
| Decision | Continue research, revise and retest, or reject. Cite at least one result and one limitation. |

## Example of a capstone finding

> I fixed the KO / PEP rule after the formation test. In this fictional record the earlier run had six closed trades, and the later run had one closed loss and another paper position still open. The two reports used the same data fields and cost assumptions. The holdout sample is small and does not confirm the earlier outcome. I would keep the rule for observation only and collect more usable evidence before running another test.

The figures in this book use synthetic prices and illustrate what each control or result means. Record the source and period of your own reports so another reader can tell the difference.

## Troubleshooting

| Symptom | First checks |
| --- | --- |
| No source in the picker | Verify the local component is running or a compatible provider is configured. Check that the source covers both symbols. |
| No z-score | Look for missing aligned inputs, a window still warming up or zero variation. |
| No closed trade | Check whether no position entered, or one entered and remained open. |
| No return value | Check whether an entry supplied a usable denominator. |
| Automatic results differ with the same seed | Compare source rows, bounds, intervals and settings, as well as the seed. |
| A paper position remains after Stop | Examine quantities and closing receipts. Stop controls the scheduled run. |

---

[Previous · Assess whether the relationship holds](14-assess-the-relationship.md) · [Edition contents](README.md)
