# How the three scores are calculated

**Exam: LSAT (120–180 scale).** Two Logical Reasoning sections + one Reading
Comprehension section (logic games retired Aug 2024).

The app answers three *different* questions and never blends them into one
number. All three are computed inside Anki's Rust engine
([`rslib/src/lsat.rs`](rslib/src/lsat.rs)) and returned to both the desktop and
mobile apps through the shared backend RPC `get_readiness` → `ReadinessResponse`
(`proto/anki/lsat.proto`). Each score is an `LsatScore { available, estimate,
low, high, confidence, sample_size, reasons }`.

| Score | Question it answers | Data source | Scale |
|-------|--------------------|-------------|-------|
| Memory | Can the student recall a fact right now? | FSRS card states | probability 0–1 |
| Performance | Can they answer a *new* exam-style question? | graded practice attempts | accuracy 0–1 |
| Readiness | What LSAT score would they get today? | performance → projection | 120–180 |

Every score carries a **point estimate**, a **likely range** (`low`/`high`), a
**confidence** indicator, a **sample size**, and human-readable **reasons**. If
there is not enough data, `available = false` and `reasons` says exactly what is
missing — the app shows *no number* rather than a guess (the "give-up rule").

---

## 1. Memory — mean FSRS retrievability

Memory is the average probability that the student can recall a reviewed card
*right now*. We do not re-implement FSRS; we read its state.

For every card that has an FSRS memory state, the engine computes current
retrievability given time elapsed since the last review:

```
R_i = FSRS.current_retrievability_seconds(state_i, elapsed_i, decay_i)
```

Then, over the `n` reviewed cards:

```
estimate   = mean(R)                      = (1/n) · Σ R_i
variance   = (1/n) · Σ (R_i − mean)²
std_err    = sqrt(variance / n)
low, high  = clamp(mean ± 1.96 · std_err, 0, 1)      # 95% CI for the mean
confidence = min(n / 100, 1)                          # grows with sample size
```

- **Range** = a 95% confidence interval for the mean recall probability. A
  noisier set of cards (mix of well- and poorly-remembered) yields a wider
  range — this is unit-tested (`wider_spread_gives_wider_range`).
- **Give-up rule:** if `n < MIN_MEMORY_CARDS` (**10**), memory is unavailable
  and reports "need at least 10 reviewed cards".

## 2. Performance — accuracy on graded questions with a binomial CI

Performance is how often the student answers *new, exam-style* LR/RC questions
correctly. Every graded attempt in the practice flow is logged to the
collection config (`lsat:attempts`) as `{correct, section, question_type,
passage}`. Over the `n` recorded attempts with `c` correct:

```
estimate   = p = c / n
std_err    = sqrt(p·(1 − p) / n)                       # normal approx. to binomial
low, high  = clamp(p ± 1.96 · std_err, 0, 1)           # 95% CI for accuracy
confidence = min(n / 100, 1)
```

- **Why this is a separate score from Memory:** remembering a flashcard does not
  mean you can answer a passage-based question that *uses* the fact. Performance
  is measured only from real graded question attempts, never from FSRS state.
- **Give-up rule:** if `n < MIN_ATTEMPTS_FOR_PERFORMANCE` (**20**), performance
  is unavailable.

## 3. Readiness — performance projected onto 120–180, gated hard

Readiness is the projected LSAT score. It is the honest bridge from
"performance accuracy" to "a number on the real scale", and it is **hidden**
until the student has genuinely broad, deep evidence.

### The give-up rule (all four must hold)

Readiness stays unavailable — and lists each unmet condition — unless:

| Gate | Constant | Threshold |
|------|----------|-----------|
| Graded practice questions (LR + RC) | `MIN_GRADED_PRACTICE_FOR_READINESS` | ≥ **200** |
| LR question-type taxonomy covered | `MIN_LR_COVERAGE_FOR_READINESS` | ≥ **50%** |
| Distinct completed RC passages | `MIN_RC_PASSAGES_FOR_READINESS` | ≥ **3** |
| A working performance model | `performance.available` | required |

Coverage is measured against the 14-type LR taxonomy (`LR_TAXONOMY`: Main Point,
Necessary/Sufficient Assumption, Strengthen, Weaken, Flaw, Inference, Method of
Reasoning, Parallel Reasoning, Parallel Flaw, Principle, Resolve/Explain, Point
at Issue, Role in Argument), so readiness requires *breadth* across question
types, not just volume.

### The projection (once unlocked)

Accuracy is mapped linearly onto the LSAT scale, and the performance interval is
carried through the *same* map so the range stays honest:

```
scale(a)  = 120 + clamp(a, 0, 1) · 60
estimate  = scale(performance.estimate)
low       = scale(performance.low)
high      = scale(performance.high)
confidence = performance.confidence
```

Example: 75% graded accuracy → 120 + 0.75·60 = **165**, with the range coming
straight from the performance CI.

### Honesty payload (the "confident number" rule)

`ReadinessResponse` ships everything needed to justify the number, never a bare
score:

- `estimate`, `low`, `high` — point estimate **and** likely range.
- `confidence` + `sample_size` — how sure, and on how much data.
- `topic_coverage` — % of the LR taxonomy covered so far.
- `reasons` — the evidence behind the number.
- `missing_data` — what is still missing.
- `next_best_step` — the single best thing to study next.
- `last_updated` — when it was computed.

**Calibration caveat (honest):** the projection is a deterministic, interval-
preserving map from measured accuracy, and confidence/interval width represent
its uncertainty. We do **not** yet claim a calibration curve of past *predicted
vs. actual official LSAT scores*, because that requires real post-test outcome
data we do not have. This is stated rather than hidden.

---

## AI scoring is separate and evaluated

The only place a model grades a student is the **Socratic Station**, where it
decides whether a free-text explanation earns credit. That output is not part of
the three scores above; it is a named-source AI (OpenAI `gpt-4o-mini`) checked
against a held-out test set and compared to a keyword baseline. With AI off, the
apps fall back to a deterministic keyword grader and all three scores still
compute. See [`lsat/eval/README.md`](lsat/eval/README.md) for the numbers.

## Where to verify

- Formulas & give-up rule: [`rslib/src/lsat.rs`](rslib/src/lsat.rs)
- Unit tests (give-up, ranges, coverage, projection, latency): same file, `mod test`
- Proto contract: `proto/anki/lsat.proto` (`LsatScore`, `ReadinessResponse`)
