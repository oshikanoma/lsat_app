# LSAT Speedrun — content layer

This folder holds the **question/content data** for the app. It serves two roles at once:

1. The **bundled original starter bank** (safe to ship — we authored it, we own the copyright).
2. The **canonical import format** for user-supplied content (bring-your-own).

See PRD §14 for the full sourcing decision. **Do not add scraped or copyrighted content here.**

## Files

| File                         | Section | Contents                                                                 |
| ---------------------------- | ------- | ------------------------------------------------------------------------ |
| `schema.json`                | —       | JSON Schema (draft 2020-12) defining the record format. Source of truth. |
| `logical_reasoning.json`     | LR      | Original Logical Reasoning questions across question types.              |
| `reading_comprehension.json` | RC      | Original RC passage(s) with attached questions.                          |
| `vocabulary.json`            | VOCAB   | Original "Word of the Day" entries with usage questions.                 |

## Provenance (required on every record)

Every item carries a `provenance` field and a `source` string. This is what keeps the app honest and shippable:

- `original` — authored for this project. **Safe to bundle and ship.**
- `user-imported` — supplied by the end user (e.g. their own free LawHub PrepTests). **Never redistributed.**
- `synthetic` — AI-generated, only under the project's AI rules (named model, validated on held-out set, beats a baseline). Clearly labeled, kept secondary.
- `licensed` — used under an explicit license (e.g. LSAC content licensing). Not used yet.

> The **shippable / AI-off build** uses only `original` + `user-imported` records.

## How it maps to the engine

- The Rust engine (`rslib`) imports these records as cards/notes in the shared collection, so **desktop and mobile** read the same content through the same engine.
- `question_type`, `difficulty`, and `skill_tags` are the features the **Performance** and **Readiness** models score against (per question type / skill).
- `provenance` lets the engine and UI filter content (e.g. exclude `synthetic` in the AI-off build).

## Validating

```bash
python3 -m json.tool lsat/content/logical_reasoning.json > /dev/null && echo OK
```

(Or validate against `schema.json` with any JSON Schema validator, e.g. `check-jsonschema`.)
