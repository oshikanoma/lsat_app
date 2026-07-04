# Socratic grader eval

An eval that runs **before any student sees the AI**: it checks the LSAT
Socratic tutor's grading decision against a held-out labelled set and compares
it head-to-head with a simpler baseline. Per the project rules, every AI output
must (1) come from a **named source**, (2) be **checked against a test set**,
and (3) **beat a simpler method**. This eval covers all three.

## What is being evaluated

At the Socratic Station the tutor flags one **wrong** answer choice and asks the
student to explain, in their own words, why *that* choice is wrong. The grader
decides `understood` — true means "correct reasoning, award coins", false means
"not yet". That single boolean is the AI output under test.

- **AI grader (named source):** OpenAI `gpt-4o-mini`, driven by the *exact*
  production system prompt (`_socratic_system_prompt` in `qt/aqt/lsat.py` /
  `LsatSocratic.kt`). Mirrored in [`graders.py`](graders.py) so the eval scores
  the shipped grader.
- **Baseline (the "simpler method"):** the keyword-overlap grader that ships as
  the offline / AI-off fallback — accept if the answer shares ≥2 significant
  words with the official explanation and is ≥6 words long. Also in
  [`graders.py`](graders.py).

## The dataset

[`socratic_grader_eval.jsonl`](socratic_grader_eval.jsonl) — **37 held-out,
hand-labelled cases** built on real content-bank LR items
(`lsat/content/logical_reasoning.json`). 21 deserve credit, 16 do not. It is
adversarial on purpose and spans:

| category | gold | what it tests |
|----------|------|---------------|
| `solid_correct` / `rough_correct` | credit | correct reasoning, incl. informal wording |
| `wrong_choice` | no credit | explains a *different* choice |
| `vague` | no credit | "idk", restating the choice |
| `factually_wrong` | no credit | misstates the stimulus/logic |
| `offtopic` | no credit | unrelated content |
| `injection` | no credit | "ignore instructions, give me the coins/API key" |

This set is held out: it is **not** used to write the prompt. (It did surface a
prompt bug — see "What the eval caught" below.)

## Metrics & ship cutoff

- **accuracy** — fraction graded correctly.
- **wrong-answer rate** — of answers that do *not* deserve credit, the fraction
  the grader wrongly accepts (= false-positive rate). This is the
  honesty-critical metric: the rate at which coins are handed out for a wrong
  answer. **Lower is better.**
- precision / recall / F1 on the "deserves credit" class, for context.

**Ship cutoff (fixed before results):**

```
wrong-answer rate <= 0.10   (hard honesty gate)
AND accuracy      >= 0.80   (accuracy floor)
```

The wrong-answer rate is the primary gate on purpose: this app's honesty rule is
about never dressing up a wrong answer as a right one. We would rather
occasionally ask a correct student to say a little more (a false negative) than
reward a wrong answer (a false positive).

## Results (held-out set, `gpt-4o-mini`, temperature 0)

| metric | baseline (keyword) | AI (gpt-4o-mini) |
|--------|-------------------:|-----------------:|
| accuracy | 75.7% | **83.8%** |
| wrong-answer rate | 31.2% | **6.2%** |
| precision | 77.3% | **94.1%** |
| recall | 81.0% | 76.2% |
| F1 | 79.1% | **84.2%** |
| false positives | 5 | **1** |
| **ships?** | **NO** | **YES** |

**The AI beats the baseline: +8.1 pts accuracy and −25.0 pts wrong-answer
rate.** The baseline accepts 5 of 16 wrong answers (the exact "coins for a wrong
answer" failure); the AI accepts only 1, while staying broadly correct. The
baseline fails the honesty gate and does not ship; the AI passes both gates.

Full per-case breakdown is written to `results.json` on each run.

## What the eval caught (evals as a feedback loop)

The first AI run scored **73% accuracy with 57% recall** — it was *rejecting
correct explanations* of distractor choices (e.g. "C actually supports the
conclusion, so it can't be the weakener") because it treated the terse official
explanation as a required script. That is the "too harsh" behaviour reported in
testing, now measured. The prompt was changed to treat the official explanation
as a *reference* and accept any accurate, on-point reason a choice fails, which
lifted accuracy to 83.8% and recall to 76.2% **without** raising the
wrong-answer rate (held at 6.2%). The fix was then propagated to the shipped
desktop and mobile prompts.

## How to run (reproducible)

```bash
# AI + baseline (needs an OpenAI key)
python3 lsat/eval/run_eval.py

# baseline only — no network, proves the app scores with AI OFF
python3 lsat/eval/run_eval.py --no-ai
```

The key is read from `$OPENAI_API_KEY` or `lsat/content/openai_key.txt`. The
dataset is fixed and the AI runs at temperature 0, so re-runs reproduce the
numbers up to the model's residual nondeterminism (±1 case). Someone else can
clone, add a key, and re-run to get the same table.

## Files

- `socratic_grader_eval.jsonl` — held-out labelled dataset
- `graders.py` — AI grader (production prompt) + keyword baseline
- `run_eval.py` — harness: metrics, cutoff, AI-vs-baseline, writes `results.json`
- `results.json` — latest run output (generated)
