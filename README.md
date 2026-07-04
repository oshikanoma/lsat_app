# homebase. — an LSAT prep app built inside Anki

`homebase.` is an LSAT preparation app built **directly inside the Anki
codebase** — not a layer on top of Anki, but real changes inside its Rust engine,
Protobuf contracts, and UI. The desktop app and the Android companion are **one
project sharing a single Rust engine** (`rslib`), the same collection, the same
FSRS scheduling, and the same AnkiWeb sync.

This is a fork of [Anki](https://apps.ankiweb.net) and is distributed under the
same license (see [License](#license)).

---

## What the app does

`homebase.` turns spaced repetition into a full LSAT study experience. When you
open it, you land on the **homebase** — an animated floating-island house you tap
to begin. From there you get:

- **Three honest scores.** Every score shows a range and the evidence behind it,
  and refuses to display until there's enough data to be trustworthy:
  - **Memory** — how well material is retained, derived from Anki's FSRS
    retrievability.
  - **Performance** — accuracy on interactive practice questions.
  - **Readiness** — overall progress toward test day.
    Tap any metric to see _why_ you got that score and how confident it is.
- **Adaptive timed lessons.** One **Start lesson** button runs a 2-hour adaptive
  session (shown as a draining hourglass) that targets your weakest area. Answer
  choices are clickable with instant correct/incorrect feedback and an
  explanation; a wrong answer moves on instead of repeating.
- **Word of the Day.** One new LSAT vocab word per calendar day, added as a
  flashcard to a dedicated `LSAT Vocab` deck, with an interactive "use it in a
  sentence" check and arrows to browse words you've learned.
- **Socratic Station.** A no-timer station that shows a wrong answer to an LSAT
  question and asks you to explain _why_ it's wrong; correct explanations earn
  coins. It runs an **AI tutor** (OpenAI `gpt-4o-mini`) that asks follow-ups and
  tailors feedback when a key is connected, and falls back to an offline
  keyword grader otherwise. A badge in the station header shows which engine is
  live, and clicking it lets you paste a key. See
  [Connecting the AI tutor](#connecting-the-ai-tutor).
- **A house you upgrade.** Coins earned from lessons and the Socratic Station buy
  cosmetic upgrades for your homebase (garden, lights, fountain, observatory,
  sunset sky, and more).

## How it works

The important architectural point: everything that matters lives inside the
**collection**, which is created and managed by the shared Rust engine.

- **Interactive LR/RC questions** are `LSAT MCQ` notetype cards in the
  `LSAT Practice::*` decks. They are tracked by FSRS just like any card, so
  Memory and mastery come straight from the engine.
- **Word of the Day** cards are the `LSAT Vocab` notetype.
- **The three scores and the give-up rule** are computed in Rust
  (`rslib/src/lsat.rs`) and exposed over Protobuf
  (`proto/anki/lsat.proto` → `LsatService.GetReadiness`). Any client on this
  engine gets identical numbers.
- **LSAT-specific data** (practice attempts, profile/plan, coins, house
  upgrades) is stored as synced collection config (`lsat:attempts`,
  `lsat:profile`, `lsat:house`), so progress follows you across devices via
  AnkiWeb login.

Because desktop and phone are the same engine writing the same collection format,
reviews merge through Anki's normal sync without being lost or double-counted. See
[`MOBILE.md`](./MOBILE.md) for the full shared-engine explanation.

### Readiness coverage rules (the give-up rule)

The Readiness score is deliberately hard to show: the engine refuses to project a
number until it has enough _and_ broad enough evidence. All of these must hold
(implemented in `rslib/src/lsat.rs`, matching [`prd.md`](./prd.md) §8.2):

| Rule                                | Threshold | Constant                            |
| ----------------------------------- | --------- | ----------------------------------- |
| Graded practice questions (LR + RC) | ≥ 200     | `MIN_GRADED_PRACTICE_FOR_READINESS` |
| LR question-type taxonomy covered   | ≥ 50%     | `MIN_LR_COVERAGE_FOR_READINESS`     |
| Distinct completed RC passages      | ≥ 3       | `MIN_RC_PASSAGES_FOR_READINESS`     |
| A working Performance model         | required  | (≥ 20 graded questions)             |

Until every rule is met, the home screen shows **exactly what's missing and how
to unlock it** (e.g. _"LR taxonomy coverage is 30% — reach 50% by practicing more
question types"_) plus a live **"% of exam covered"** readout, instead of a made-up
score. Once unlocked, Readiness projects the measured graded accuracy onto the real
**120–180** LSAT scale, carrying the confidence interval through so the range stays
honest. Each answer records the metadata the rule needs — section, LR
`question_type` (for taxonomy coverage) and, for RC, a stable passage id — into the
synced `lsat:attempts` config, so coverage is identical on desktop and phone.

The exact formulas for all three scores (FSRS-mean memory with a 95% CI, binomial
performance accuracy, and the readiness projection) are documented in
[`SCORING.md`](./SCORING.md).

### AI eval (Socratic grader)

The one place a model grades a student — the Socratic Station — is checked
against a held-out labelled test set and compared head-to-head with a keyword
baseline before any student sees it. On 37 held-out cases the AI grader
(`gpt-4o-mini`) hits **83.8% accuracy at a 6.2% wrong-answer rate**, beating the
keyword baseline (75.7% / 31.2%) by **+8.1 pts accuracy and −25 pts
wrong-answer rate**, and passing the ship cutoff the baseline fails. With AI
off, both apps fall back to the deterministic keyword grader and all three
scores still compute. Dataset, harness, cutoff and reproduction steps:
[`lsat/eval/README.md`](./lsat/eval/README.md).

### LR question-type mastery & adaptive lessons

Every Logical Reasoning question carries an LR-Bible-style type (Must Be True,
Weaken, Strengthen, Assumption, Flaw, Parallel Reasoning, Principle, …). Because
each graded answer already stores its `question_type` in the synced
`lsat:attempts` config, the app tracks per-type accuracy with no extra bookkeeping:

- **Dashboard breakdown.** The home screen shows a "Logical Reasoning by question
  type" list, weakest first. It follows the same honesty rule as the main scores —
  a type's accuracy is hidden until it has at least `MIN_TYPE_ATTEMPTS` (5) graded
  answers, showing _"N more to score"_ instead of a shaky percentage.
- **Adaptive selection.** Timed lessons prefetch several due LR cards and serve the
  one whose type most needs work (untested types first, then lowest accuracy),
  mirroring the existing weakest-_section_-first logic at question-type
  granularity. This is a deterministic heuristic computed in
  `_weakest_type_index` (desktop) / `weakestTypeIndex` (phone) — no network or API
  key required, and it reads the same synced attempt log on both platforms.

Content is bundled under the project's provenance rules (`original` /
`user-imported` / `synthetic`); explanations are **not** scraped from copyrighted
sources such as the LR Bible.

### Connecting the AI tutor

The Socratic Station uses an AI tutor (OpenAI `gpt-4o-mini`) when a key is
connected; without one it falls back to an offline keyword grader. AI is
strictly opt-in, so the default build ships in the offline ("AI-off") mode.

There are two ways to provide a key:

- **In-app (recommended, works on desktop and phone).** Open the Socratic
  Station and click the engine badge in the header ("Offline grader" → paste key
  → **Save**). The badge flips to "AI tutor" once connected. The key is stored
  **locally on that device only and is never synced** to AnkiWeb — desktop keeps
  it in the Anki profile manager (`mw.pm`), the phone in a private
  `SharedPreferences` file. Clear the field and save to disconnect.
- **Environment variable (desktop only).** Launch with `OPENAI_API_KEY` (or
  `LSAT_OPENAI_API_KEY`) exported; it takes precedence over a stored key.

The tutor is capped at `MAX_SOCRATIC_TURNS` (3) messages per question and is
tuned to accept a good explanation quickly rather than badger. Its coaching text
is generated on the fly and is never written into the bundled content, so it
doesn't affect content provenance.

### Performance & latency

The scoring is a pure Rust computation over the collection, so it's fast enough to
run on every home-screen render:

- **Readiness/score computation:** ≈ **0.5 ms** average per call on a seeded
  500-question collection (unoptimized debug build; faster in release). Measured by
  the reproducible benchmark test:

  ```bash
  cargo test -p anki --lib lsat::test::readiness_scoring_latency_is_low -- --nocapture
  # prints e.g. "lsat_readiness avg latency over 50 runs: 480µs"
  ```

  The test also asserts the call stays under 100 ms, guarding against regressions.
  The live desktop app logs the same measurement each render
  (`lsat: readiness scoring took … ms`).
- **Sync latency:** progress is pushed to AnkiWeb **after every coin-earning
  action** (and on app open/close). The upload is debounced (~1.2 s on desktop) so a
  burst of correct answers coalesces into a single sync rather than one per answer;
  the actual round-trip is network-bound and runs off the UI thread.
- **Live refresh:** while the home screen is open, both desktop and phone quietly
  pull from AnkiWeb every ~25 s and re-render **only if the collection actually
  changed**, so progress from another device appears on its own — no Sign-in/out and
  no Sync button. Lessons, the Socratic Station and reviews are never interrupted,
  and a diverged full sync is still left to the manual Sync button.

---

## Download and install (no building required)

If you just want to **use** `homebase.` — not build it from source — grab a
prebuilt installer from the repo's
**[Releases page](https://github.com/oshikanoma/lsat_app/releases/latest)**.
No developer tools required; download, open, done.

Both installers are self-contained — they carry the shared engine and the LSAT
content and install into the normal per-app location with no separate setup — so a
fresh install starts from a clean slate and your progress lives on your AnkiWeb
account. Each release publishes the **SHA-256** of every artifact; to confirm a
download is intact before opening it, compute the hash and compare it against the
value shown on the release page:

```bash
shasum -a 256 anki-26.05-mac-apple.dmg          # macOS installer
shasum -a 256 homebase-26.05-android-arm64.apk  # Android installer
```

### macOS (desktop)

1. On the [latest release](https://github.com/oshikanoma/lsat_app/releases/latest),
   download **`anki-26.05-mac-apple.dmg`** (Apple Silicon: M1/M2/M3/M4). Intel
   Macs aren't prebuilt yet — build from source (below) or ask for an Intel
   `.dmg`.
2. Double-click the downloaded `.dmg`, then drag **Anki** into your
   **Applications** folder. (The app is packaged under Anki's name — that's the
   engine `homebase.` runs on — but it opens straight to the LSAT home screen.)
3. **First launch only:** because this build isn't signed with a paid Apple
   Developer certificate, macOS will refuse to open it the first time with a
   message like _"Apple could not verify … is free of malware."_ This is
   expected. To get past it once:
   - Open **System Settings → Privacy & Security**, scroll to the bottom, and
     click **Open Anyway** next to the Anki message, then confirm with **Open**.
   - (Alternatively: **Control-click** the app in Applications → **Open** →
     **Open**.)

   After that first time it launches normally with a double-click, forever.

> Why the warning? Signing an app so it opens with zero friction requires an
> Apple Developer ID ($99/year) and notarization. This build is _ad-hoc signed_
> instead, which is free but triggers the one-time prompt above. The app itself
> is unchanged.

### Android (phone)

1. On the [latest release](https://github.com/oshikanoma/lsat_app/releases/latest),
   download the file ending in **`.apk`** onto your Android phone.
2. Tap the downloaded file. Android will ask permission to _"install unknown
   apps"_ from your browser or Files app — allow it (this is the normal prompt
   for any app installed outside the Play Store), then tap **Install**.
3. Open the app; it launches to the same `homebase.` home screen and syncs with
   desktop via your AnkiWeb login.

---

## Running the desktop app

**Prerequisites:** the standard Anki dev toolchain (Rust via `rustup`, Python
3.9+, and the build tooling Anki uses). See
[docs/development.md](./docs/development.md) for a first-time setup.

From the repository root:

```bash
./run
```

This builds the Rust engine, the Protobuf bindings, and the SvelteKit UI, then
launches the app. It opens **straight to the LSAT home screen** — the first launch
runs a short onboarding (your name, study-plan start date, and a diagnostic quiz).

To sync your progress, use the **Sign in / Synced** button in the top-right of the
home screen and log in with your AnkiWeb account.

### Rebuilding just the UI

If you only changed the Svelte pages under `ts/routes/lsat-*`:

```bash
./ninja sveltekit
```

---

## Running the mobile (Android) app

The Android app is a custom AnkiDroid client compiled against **this fork's Rust
engine**, so it shows the same home screen, lessons, Socratic Station, Word of the
Day, and the same three scores. It lives outside this repo (kept in
`~/lsat-mobile`) because the APK is built in the AnkiDroid projects — that is the
intended "share the engine" boundary.

**Prerequisites (one-time):** JDK 17, the Android SDK + command-line tools, an
NDK, `cargo-ndk`, and the Android Rust targets. The paths are captured in
[`mobile-env.sh`](./mobile-env.sh); source it before any Android build:

```bash
source ./mobile-env.sh   # sets JAVA_HOME, ANDROID_HOME, NDK, MOBILE_DIR, PATH
```

### Build the APK (one command, reproducible)

The whole chain — UI bundle → Android assets → APK compiled against the shared
Rust engine — is codified in [`build_phone.sh`](./build_phone.sh):

```bash
./build_phone.sh
```

It prints the resulting artifact's path, size and **SHA-256** so the build is
verifiable evidence rather than a manual sequence, e.g.:

```
==> Build succeeded. Artifact evidence:
    path:   ~/lsat-mobile/Anki-Android/AnkiDroid/build/outputs/apk/full/debug/AnkiDroid-full-arm64-v8a-debug.apk
    size:   58M
    sha256: <hash>
```

Then install and launch:

```bash
adb install -r -d \
  ~/lsat-mobile/Anki-Android/AnkiDroid/build/outputs/apk/full/debug/AnkiDroid-full-arm64-v8a-debug.apk
adb shell am start -n com.ichi2.anki.debug/com.ichi2.anki.IntentHandler
```

<details><summary>Or run the steps by hand</summary>

```bash
# 1. Build the desktop UI bundle and copy it into the Android assets
#    (also injects the native bridge shim the WebView needs).
./ninja sveltekit
./sync_lsat_web.sh

# 2. Build the Android APK against the shared engine.
source ./mobile-env.sh
cd "$MOBILE_DIR/Anki-Android"
./gradlew :AnkiDroid:assembleFullDebug

# 3. Install it and launch.
adb install -r -d \
  AnkiDroid/build/outputs/apk/full/debug/AnkiDroid-full-arm64-v8a-debug.apk
adb shell am start -n com.ichi2.anki.debug/com.ichi2.anki.IntentHandler
```

</details>

The app launches to the same `homebase.` home screen. On a fresh launch it opens
on the decorated-house hub; tap it to reveal the menu.

> Whenever you change the Svelte pages, re-run `./build_phone.sh` (or steps 1–3 by
> hand) so the WebView picks up the new UI.

### Booting an emulator

```bash
source ./mobile-env.sh
emulator -avd <your_avd_name>          # e.g. created with avdmanager
adb devices                             # confirm the device is listed
```

### Syncing across devices

Log into the **same AnkiWeb account** on desktop and phone via the **Sign in**
button. Cards, FSRS state, scores, and your LSAT progress (coins, plan, house)
sync both ways and work offline until the connection returns.

For the deeper "one engine, two apps" rationale and the iOS path, see
[`MOBILE.md`](./MOBILE.md). Product goals and scoring rules live in
[`prd.md`](./prd.md).

---

## License

This project is a fork of Anki and is licensed under AGPL-3.0-or-later. See
[LICENSE](./LICENSE). Anki is developed by
[Ankitects](https://apps.ankiweb.net); the original contributors are listed in
[CONTRIBUTORS](./CONTRIBUTORS).
