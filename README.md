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
  Tap any metric to see *why* you got that score and how confident it is.
- **Adaptive timed lessons.** One **Start lesson** button runs a 2-hour adaptive
  session (shown as a draining hourglass) that targets your weakest area. Answer
  choices are clickable with instant correct/incorrect feedback and an
  explanation; a wrong answer moves on instead of repeating.
- **Word of the Day.** One new LSAT vocab word per calendar day, added as a
  flashcard to a dedicated `LSAT Vocab` deck, with an interactive "use it in a
  sentence" check and arrows to browse words you've learned.
- **Socratic Station.** A no-timer station that shows a wrong answer to an LSAT
  question and asks you to explain *why* it's wrong; correct explanations earn
  coins.
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

### Build and install onto an emulator or device

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

The app launches to the same `homebase.` home screen. On a fresh launch it opens
on the decorated-house hub; tap it to reveal the menu.

> Whenever you change the Svelte pages, re-run steps 1–3 (rebuild the bundle,
> `sync_lsat_web.sh`, then rebuild/reinstall the APK) so the WebView picks up the
> new UI.

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
