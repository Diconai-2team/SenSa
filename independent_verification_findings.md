# Independent verification & extended analysis of the 13-adic soft square-class cluster

Computed `p(n) mod (13·17·19·23·29·31·37·41)` from scratch via the pentagonal-number
recurrence in C, for `n` up to `N = 5,000,000`, then re-derived every statistic in `numpy`.
This is fully independent of the GPT pipeline. Sanity checks pass
(`p(100) = 190569292` reproduced exactly; `p(0..14)` correct).

## 1. The core claim reproduces exactly

| quantity | GPT draft | this work (independent) |
|---|---|---|
| cluster mod 169 (B≥1.2), at 1M/3M/5M | {19,58,71,84,97,136,162} | **identical at all three cutoffs** |
| Δ₁₃ = B_QR/0 − B_NQR at 1M | 0.316 | 0.3157 |
| Δ₁₃ at 3M | 0.241 | 0.2407 |
| Δ₁₃ at 5M | 0.210 | 0.2099 |
| threshold-free rank: top-7 t-classes | {0}∪QR | **{0,1,3,4,9,10,12} = {0}∪QR, clean gap** |

The computation is sound — no error in the original work. The QR/NQR separation is clean:
lowest QR-class B = 1.206 sits well above highest NQR-class B = 1.090.

## 2. Normalization: the contrast is the right object (the raw B-ratio is not)

The **global** rate of `13 | p(n)` over all n is already above baseline:
B_global ≈ 1.043 → 1.039 (1M→5M), i.e. p(n) is not perfectly equidistributed mod 13 in this range.
So "B > 1" everywhere is partly a global offset and should not be read as branch-specific.
The branch n≡6 (mod 13) is nonetheless the clear standout (B = 1.184 vs ~1.00–1.05 for other
residues mod 13). **Conclusion:** keep reporting the QR/0−NQR *contrast* Δ, which cancels the
global offset, and drop any framing that leans on absolute B-ratios.

## 3. Controls, done properly — ℓ=13 is genuinely special (this survives scrutiny)

I removed the assumption that QR is always the favored side and, for each prime, ranked all
square-classes and computed the contrast with a proper standard error (N=5M, same range for all):

| ℓ | Δ (signed) | Z(Δ) | favored side | top-k = {0}∪QR? |
|---|---|---|---|---|
| **13** | **+0.210** | **17.5** | QR/0 | **yes (clean)** |
| 17 | +0.028 | 1.9 | QR/0 | no |
| 19 | −0.002 | −0.1 | – | no |
| 23 | −0.001 | −0.0 | – | no |
| 29 | −0.056 | −2.1 | NQR | no |
| 31 | +0.037 | 1.3 | QR/0 | no |
| 37 | +0.015 | 0.5 | QR/0 | no |
| 41 | −0.041 | −1.1 | NQR | no |

I had suspected the controls might be the *same* phenomenon with a flipped favored side
(which would have made 13 non-special). **The data reject that:** every control has |Z| < 2.2 and
none shows the clean square-class ranking that 13 does. 13's |Δ| is 3.7× the largest control and
~10× more significant. So "ℓ=13 is an outlier" holds up. (Caveat: this coarse branch-average
statistic is evidently insensitive to the sparse Atkin congruences known at 17–31; 13 stands out
here likely because of its especially strong ℓ-adic / mod-169 Hecke structure — Folsom–Kent–Ono.)

## 4. Decisive new diagnostic: disjoint-window (local) contrast

Cumulative Δ(N) is dominated by small n, so its decline is ambiguous. Measuring Δ in **disjoint
windows** of n separates "small-n artifact" from "persistent effect":

| window of n | local Δ₁₃ | Z |
|---|---|---|
| 0–1M | 0.316 | 11.4 |
| 1–2M | 0.232 | 8.6 |
| 2–3M | 0.174 | 6.5 |
| 3–4M | 0.177 | 6.7 |
| 4–5M | **0.150** | **5.7** |

The effect is **not** a small-n artifact: in the pure 4–5M window the contrast is still Δ≈0.15
at Z≈5.7. It declines but persists locally. This is stronger evidence than anything in the current
draft and should replace the (incorrect) "Z-score grows ⇒ not noise" argument.

## 5. Asymptotics: the data now favor slow decay **to zero**, not a positive limit

A power-law fit on my 1–5M points alone gives

> Δ₁₃(N) ≈ 10.9 · N^(−0.255)  → 0

and **extrapolates correctly to the user's independently-computed values**:
predicts 10M → 0.178 (actual 0.183), 20M → 0.149 (actual 0.154). A pure decay-to-zero model with
no constant term already fits a 4× extrapolation. Predicted: ≈0.10 at 1e8, ≈0.055 at 1e9, ≈0.009
at 1e12. So the honest statement is sharper than "could be either": the contrast almost certainly
**decays to zero**, but as a power law so slow it stays numerically visible at any feasible N.
(A tiny positive limit cannot be formally excluded from 7 points, but it is not needed to fit the data.)

## Recommended edits to the draft

1. **Cut the Z-score argument** ("not a small-sample artifact because Z grows"). It's a logical
   error — Z grows with N for any fixed bias. Replace with the windowed-contrast table (§4).
2. **Reframe asymptotics** from "undecided" to "consistent with, and best fit by, slow
   power-law decay Δ ~ N^(−0.25) to zero; the fit predicts the 10M/20M points."
3. **Strengthen the controls section** with the signed-Δ + Z table (§3) and state explicitly that
   the QR favored-side is not generic — only 13 shows the clean ranking.
4. **Soften the novelty framing.** The square-class organizing principle (square class of 1−24β)
   is a *published theorem* for ℓ=13 (Atkin; Ahlgren–Allen–Tang), and mod-169 Hecke structure is
   in Folsom–Kent–Ono. The contribution is the *soft/statistical* measurement of a known structure,
   plus the empirical decay law — not a new congruence family.

Figures: `fig_decay.png`, `fig_windows.png`, `fig_controls.png`. Scripts: `pgen.c`, `analyze.py`,
`analyze2.py`, `plots.py` (reproducible end-to-end).
