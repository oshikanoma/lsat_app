# elle. on mobile — two apps, one engine

This document explains how the LSAT prep app runs on a phone **without rewriting
the scheduler**, how desktop and phone stay in sync, and the exact steps to build
the Android companion.

The short version: the desktop app and the phone app are **not two projects**.
They share the same Rust engine (`rslib`), the same collection (cards, decks,
FSRS scheduling state, and our LSAT config), and the same sync. The phone is a
companion for reviewing on the go and checking readiness.

---

## 1. Why this already shares the engine

Everything that matters lives inside the collection, which is created and managed
by the shared Rust engine — the same crate that AnkiDroid and Anki-compatible iOS
clients run on the device:

| Thing | Where it lives | Shared? |
| --- | --- | --- |
| LSAT practice questions (LR/RC) | `LSAT MCQ` notetype cards in `LSAT Practice::*` decks | Yes — normal cards |
| Word of the Day vocab | `LSAT Vocab` notetype cards | Yes — normal cards |
| Spaced-repetition state | FSRS memory state on each card | Yes — engine-owned |
| Practice attempts (Performance) | `lsat:attempts` collection config key | Yes — synced config |
| Profile / plan / pet / coins | `lsat:profile`, `lsat:pet` config keys | Yes — synced config |
| The 3 scores + give-up rule | `rslib/src/lsat.rs` → `LsatService.GetReadiness` | Yes — engine RPC |

Because the three scores are computed in `rslib` and exposed through the backend
service `BackendLsatService` (see `proto/anki/lsat.proto`), **any** client built
on this engine — desktop or phone — gets the identical Memory / Performance /
Readiness numbers, ranges, and the same "refuse to score without enough data"
give-up rule. Nothing is reimplemented in Kotlin/Swift/JS.

### The interactive questions work on the phone too

The click-to-answer MCQ experience is not locked inside the desktop Svelte page.
It is baked into the **card template** (`_MCQ_QFMT` / `_MCQ_AFMT` / `_MCQ_CSS` in
`qt/aqt/lsat.py`). Card templates render in a WebView on every client, including
AnkiDroid, so the same synced card is tappable with instant correct/incorrect
feedback and an explanation on the phone — driven by the shared engine's
scheduler, not a mobile reimplementation.

---

## 2. What the phone companion does (and how each requirement is met)

- **Runs real review sessions on the same deck** — AnkiDroid opens the synced
  `LSAT Practice::*` and `LSAT Vocab` decks and schedules them with the shared
  FSRS engine. Reviews are real reviews, logged like any other.
- **Two-way sync** — a review on the phone updates the card's FSRS state and the
  review log; on next sync the desktop sees it, and vice versa. Because both sides
  are the same engine writing the same collection format, reviews merge without
  double-counting (this is exactly what stock Anki ↔ AnkiDroid sync already does).
- **Works offline** — AnkiDroid keeps a full local collection. You can study on a
  plane; the queued changes sync when the connection returns.
- **Same three scores, same ranges, same give-up rule** — computed by
  `LsatService.GetReadiness` in the shared engine, so identical on both devices.

---

## 3. Two ways to ship Android

### Path A — fastest: stock AnkiDroid + AnkiWeb (review + sync today)

1. Install AnkiDroid from Google Play / F-Droid.
2. Sync the desktop app to AnkiWeb (log in, `Sync`).
3. In AnkiDroid, log into the **same AnkiWeb account** and sync.

You now review the exact same LSAT cards on the phone, offline-capable, syncing
both ways. The interactive MCQ template renders and is tappable. What stock
AnkiDroid does **not** show is our custom home screen (scores dashboard, pet,
Socratic Station) — for that, use Path B.

### Path B — full companion: AnkiDroid built on *this* engine

This gives the phone the LSAT scores UI (and any other engine feature) by
compiling AnkiDroid against this fork's `rslib`.

AnkiDroid consumes the Rust engine through the **Anki-Android-Backend** project,
which compiles the `anki` crate into an Android `.so` and generates the Kotlin
bindings from the `.proto` files (our `lsat.proto` included).

```bash
# 1. Get the two Android repos
git clone https://github.com/ankidroid/Anki-Android-Backend.git
git clone https://github.com/ankidroid/Anki-Android.git

# 2. Point the backend at THIS engine instead of upstream Anki.
#    In Anki-Android-Backend, set the Anki source to this repo
#    (submodule 'anki' / the ANKI_SRC / rust ref it pins) so it builds
#    rslib from here, including rslib/src/lsat.rs and proto/anki/lsat.proto.

# 3. Build the backend .so + bindings (installs into the local Maven repo)
cd Anki-Android-Backend
./gradlew assembleRelease publishToMavenLocal

# 4. Build the AnkiDroid APK against that backend
cd ../Anki-Android
./gradlew assembleDebug
# APK: AnkiDroid/build/outputs/apk/debug/AnkiDroid-debug.apk
```

Then `adb install` the APK, log into the same AnkiWeb account, and sync. The
Kotlin side can call `backend.getReadiness(...)` (generated from `lsat.proto`) to
render the three scores natively; the cards themselves already render the
interactive template.

> Note: the actual APK build happens in the AnkiDroid repos, not in this desktop
> repo — that is the intended "share the engine" boundary. This repo is the
> engine + desktop client; step 2 is where you wire the phone build to it.

---

## 4. iOS

Same principle: run this fork's Rust backend on the device through its **C
interface (FFI)** — the approach Anki-compatible iOS clients use. Build `rslib`
for the iOS targets (`aarch64-apple-ios`, `aarch64-apple-ios-sim`) as a static
lib, call it from Swift over the FFI boundary, and render the `LSAT MCQ` /
`LSAT Vocab` templates in a `WKWebView`. Scores come from the same
`GetReadiness` RPC; sync uses the same AnkiWeb endpoint.

---

## 5. Sync integrity (no lost or double-counted reviews)

We use Anki's existing sync. Reviews flow between devices as review-log entries
plus card-state updates keyed by card id and USN (update sequence number), which
is how the engine already prevents double-application. Our LSAT-specific data
(`lsat:attempts`, `lsat:profile`, `lsat:pet`) rides along as synced collection
config, so Performance history, the study plan, coins, and the pet are consistent
across desktop and phone. Rewriting the scheduler on the client instead of
sharing this Rust engine would break this guarantee — which is exactly why we
don't.
