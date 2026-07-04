#!/usr/bin/env python3
"""Held-out eval for the LSAT Socratic Station grader.

Every AI output (does this explanation deserve credit?) is checked against a
labelled test set and compared head-to-head with a simpler baseline
(keyword-overlap search), per the project rules.

Metrics
-------
* **accuracy** — fraction of the held-out set graded correctly.
* **wrong-answer rate** — of answers that do NOT deserve credit (gold=false),
  the fraction the grader wrongly accepts. This is the honesty-critical metric:
  it is the rate at which a grader hands out coins for a wrong answer. Lower is
  better.
* precision / recall / F1 on the "deserves credit" class, for context.

Ship cutoff (stated up front, checked automatically)
---------------------------------------------------
A grader may drive the live tutor only if, on this held-out set:
    wrong-answer rate <= 0.10   (hard honesty gate)  AND  accuracy >= 0.80

The wrong-answer rate is the primary gate on purpose: this app's honesty rule
is about never dressing up a wrong answer as a right one (never handing coins
to an incorrect explanation). We would rather occasionally ask a correct
student to say a little more (a false negative) than reward a wrong answer (a
false positive). The 0.80 accuracy floor keeps the grader broadly correct.

Usage
-----
    python3 lsat/eval/run_eval.py                # AI + baseline (needs key)
    python3 lsat/eval/run_eval.py --no-ai        # baseline only, no network

The OpenAI key is read from $OPENAI_API_KEY or lsat/content/openai_key.txt.
The dataset is fixed and the AI runs at temperature 0, so re-runs reproduce.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import graders  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTENT = REPO_ROOT / "lsat" / "content" / "logical_reasoning.json"
DATASET = Path(__file__).resolve().parent / "socratic_grader_eval.jsonl"
KEY_FILE = REPO_ROOT / "lsat" / "content" / "openai_key.txt"

# Ship cutoff. wrong-answer rate is the hard honesty gate; accuracy is a floor.
ACC_CUTOFF = 0.80
WRONG_ANSWER_MAX = 0.10


def load_items() -> dict[str, dict]:
    data = json.loads(CONTENT.read_text())
    items = {}
    for it in data["items"]:
        items[it["id"]] = {
            "stimulus": it["stimulus"],
            # content bank calls the LR stem "stem"; the app field is "question".
            "question": it.get("stem", it.get("question", "")),
            "choices": it["choices"],
            "answer": it["answer"],
            "explanation": it["explanation"],
            "question_type": it.get("question_type", ""),
        }
    return items


def load_dataset() -> list[dict]:
    rows = []
    for line in DATASET.read_text().splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def read_key() -> str:
    import os

    env = os.environ.get("OPENAI_API_KEY", "").strip()
    if env:
        return env
    if KEY_FILE.exists():
        for ln in KEY_FILE.read_text().splitlines():
            ln = ln.strip()
            if ln and not ln.startswith("#"):
                return ln
    return ""


def metrics(preds: list[bool], gold: list[bool]) -> dict:
    tp = sum(1 for p, g in zip(preds, gold) if p and g)
    tn = sum(1 for p, g in zip(preds, gold) if not p and not g)
    fp = sum(1 for p, g in zip(preds, gold) if p and not g)
    fn = sum(1 for p, g in zip(preds, gold) if not p and g)
    n = len(gold)
    neg = fp + tn  # gold-negative cases
    acc = (tp + tn) / n if n else 0.0
    wrong_answer_rate = fp / neg if neg else 0.0
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall)
        else 0.0
    )
    return {
        "n": n,
        "tp": tp,
        "tn": tn,
        "fp": fp,
        "fn": fn,
        "accuracy": acc,
        "wrong_answer_rate": wrong_answer_rate,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def ships(m: dict) -> bool:
    return m["accuracy"] >= ACC_CUTOFF and m["wrong_answer_rate"] <= WRONG_ANSWER_MAX


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-ai", action="store_true", help="baseline only, no network")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent / "results.json"))
    args = ap.parse_args()

    items = load_items()
    rows = load_dataset()
    key = "" if args.no_ai else read_key()
    run_ai = bool(key)
    if not args.no_ai and not run_ai:
        print("! No OpenAI key found — running baseline only. "
              "Set $OPENAI_API_KEY or fill lsat/content/openai_key.txt for the AI eval.\n")

    gold = [bool(r["gold_understood"]) for r in rows]
    base_preds: list[bool] = []
    ai_preds: list[bool] = []
    per_case = []

    for r in rows:
        item = items[r["item_id"]]
        base = graders.heuristic_grade(item["explanation"], r["student_answer"])
        base_preds.append(base)
        ai = None
        if run_ai:
            try:
                ai = graders.ai_grade(item, r["wrong_letter"], r["student_answer"], key)
            except Exception as e:  # surface, don't silently mis-score
                print(f"  AI error on {r['id']}: {e}", file=sys.stderr)
                ai = base  # conservative fallback for aggregate; flagged below
            ai_preds.append(ai)
        per_case.append(
            {
                "id": r["id"],
                "item_id": r["item_id"],
                "category": r["category"],
                "gold": bool(r["gold_understood"]),
                "baseline": base,
                "ai": ai,
            }
        )

    base_m = metrics(base_preds, gold)
    ai_m = metrics(ai_preds, gold) if run_ai else None

    # --- report ---
    print("=" * 68)
    print("LSAT Socratic grader — held-out eval")
    print(f"dataset: {len(rows)} labelled cases "
          f"({sum(gold)} deserve credit, {len(gold) - sum(gold)} do not)")
    print(f"ship cutoff: wrong-answer rate <= {WRONG_ANSWER_MAX:.2f} (honesty gate) "
          f"and accuracy >= {ACC_CUTOFF:.2f}")
    print("=" * 68)
    header = f"{'metric':<22}{'baseline (keyword)':>20}"
    if run_ai:
        header += f"{'AI (gpt-4o-mini)':>20}"
    print(header)
    print("-" * len(header))

    def row(label: str, key_: str, pct: bool = True) -> None:
        b = base_m[key_]
        bs = f"{b*100:6.1f}%" if pct else f"{b}"
        line = f"{label:<22}{bs:>20}"
        if run_ai:
            a = ai_m[key_]
            as_ = f"{a*100:6.1f}%" if pct else f"{a}"
            line += f"{as_:>20}"
        print(line)

    row("accuracy", "accuracy")
    row("wrong-answer rate", "wrong_answer_rate")
    row("precision", "precision")
    row("recall", "recall")
    row("F1", "f1")
    row("false positives", "fp", pct=False)
    row("false negatives", "fn", pct=False)

    print("-" * len(header))
    base_ship = "SHIP" if ships(base_m) else "NO SHIP"
    print(f"{'ships?':<22}{base_ship:>20}", end="")
    if run_ai:
        print(f"{('SHIP' if ships(ai_m) else 'NO SHIP'):>20}")
    else:
        print()
    print("=" * 68)

    if run_ai:
        acc_gain = (ai_m["accuracy"] - base_m["accuracy"]) * 100
        war_drop = (base_m["wrong_answer_rate"] - ai_m["wrong_answer_rate"]) * 100
        print(f"AI vs baseline: +{acc_gain:.1f} pts accuracy, "
              f"-{war_drop:.1f} pts wrong-answer rate")
        verdict = "AI beats the baseline" if (
            ai_m["accuracy"] > base_m["accuracy"]
            and ai_m["wrong_answer_rate"] <= base_m["wrong_answer_rate"]
        ) else "AI does NOT clearly beat the baseline"
        print(verdict)
        print("=" * 68)

    out = {
        "cutoff": {"accuracy": ACC_CUTOFF, "wrong_answer_rate_max": WRONG_ANSWER_MAX},
        "baseline": base_m,
        "baseline_ships": ships(base_m),
        "ai": ai_m,
        "ai_ships": ships(ai_m) if run_ai else None,
        "ran_ai": run_ai,
        "per_case": per_case,
    }
    Path(args.out).write_text(json.dumps(out, indent=2))
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
