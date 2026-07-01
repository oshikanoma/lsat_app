# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""LSAT prep desktop integration.

Design (per product spec):

- Vocabulary is the only thing that lives as Anki flashcards. A new
  "word of the day" is added to the *LSAT Vocab* deck once per calendar day,
  so the deck grows into a personal vocab bank reviewed with spaced repetition
  (this feeds the Memory score via FSRS).
- Logical Reasoning / Reading Comprehension ARE the primary spaced-repetition
  content: they are real Anki cards graded through FSRS (Memory + mastery), but
  answered interactively (click a choice, get immediate feedback) instead of
  flipping. Each graded answer is also logged for the Performance score.
- The LSAT home screen is the app's main landing screen (see `LsatHome`).
- Login + cross-device progress uses Anki's built-in AnkiWeb sync.
"""

from __future__ import annotations

import html
import json
import os
import re
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import aqt
from anki.collection import Collection
from aqt.operations import QueryOp
from aqt.qt import (
    QDialog,
    QDialogButtonBox,
    QTextBrowser,
    QVBoxLayout,
    qconnect,
)
from aqt.sound import av_player
from aqt.toolbar import BottomBar
from aqt.utils import showWarning, tooltip

VOCAB_DECK = "LSAT Vocab"
_CFG_WORDS = "lsat:wotd_words"  # list[str] of words already added, in order
_CFG_DATE = "lsat:wotd_date"  # last calendar day a word was auto-added


# --- content loading -------------------------------------------------------


def _content_dir() -> Path | None:
    """Locate the bundled `lsat/content` directory across dev/install layouts."""
    candidates: list[Path] = []
    if env := os.environ.get("ANKI_LSAT_CONTENT_DIR"):
        candidates.append(Path(env))
    candidates.append(Path.cwd() / "lsat" / "content")
    here = Path(__file__).resolve()
    candidates.append(here.parents[2] / "lsat" / "content")
    candidates.append(here.parents[3] / "lsat" / "content")
    # Bundled copy shipped inside the aqt package (installer layout).
    candidates.append(here.parent / "lsat_content")
    for path in candidates:
        if path.is_dir():
            return path
    return None


def _load_vocab() -> list[dict[str, Any]]:
    content_dir = _content_dir()
    if content_dir is None:
        return []
    path = content_dir / "vocabulary.json"
    if not path.exists():
        return []
    return json.loads(path.read_text()).get("items", [])


VOCAB_NOTETYPE = "LSAT Vocab"

# Shared maroon + beige look so the flashcard reviewer matches the rest of the
# app. Kept in sync with the Svelte pages' palette.
_VOCAB_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Jost:wght@400;500;600;700;800&display=swap');
.card {
  font-family: 'Jost', -apple-system, 'Segoe UI', system-ui, sans-serif;
  font-size: 18px;
  color: #2c1b1e;
  background: #f6edda;
  padding: 28px 22px;
  line-height: 1.55;
}
.lsat-word {
  font-size: 34px;
  font-weight: 800;
  color: #4a0d18;
  letter-spacing: 0.01em;
}
.lsat-pos {
  font-style: italic;
  color: #7a6a63;
  margin-top: 4px;
}
hr#answer {
  border: none;
  border-top: 1px solid #ece0c2;
  margin: 18px 0;
}
.lsat-def { margin-top: 6px; }
.lsat-example {
  margin-top: 14px;
  font-style: italic;
  color: #6e1423;
}
"""


def _ensure_vocab_notetype(col: Collection) -> Any:
    existing = col.models.by_name(VOCAB_NOTETYPE)
    if existing:
        return existing
    m = col.models.new(VOCAB_NOTETYPE)
    for fname in ["Word", "PartOfSpeech", "Definition", "Example"]:
        col.models.add_field(m, col.models.new_field(fname))
    template = col.models.new_template("Card 1")
    template["qfmt"] = (
        '<div class="lsat-word">{{Word}}</div>'
        '<div class="lsat-pos">{{PartOfSpeech}}</div>'
    )
    template["afmt"] = (
        "{{FrontSide}}<hr id=answer>"
        '<div class="lsat-def">{{Definition}}</div>'
        '<div class="lsat-example">{{Example}}</div>'
    )
    col.models.add_template(m, template)
    m["css"] = _VOCAB_CSS
    col.models.add(m)
    return col.models.by_name(VOCAB_NOTETYPE)


def _add_vocab_card(col: Collection, item: dict[str, Any]) -> None:
    notetype = _ensure_vocab_notetype(col)
    deck_id = col.decks.id(VOCAB_DECK)
    note = col.new_note(notetype)
    note["Word"] = item["word"]
    note["PartOfSpeech"] = item.get("part_of_speech", "")
    note["Definition"] = item["definition"]
    note["Example"] = item.get("example", "")
    note.tags = ["lsat", "lsat::vocab"]
    col.add_note(note, deck_id)


def _ensure_word_of_the_day(col: Collection, *, force: bool = False) -> dict[str, Any] | None:
    """Add at most one new vocab word per calendar day.

    With `force=True`, add the next unused word immediately (used by the
    "Add another word" button so the bank can be grown on demand).
    Returns the word that was added, or None if nothing was added.
    """
    words = _load_vocab()
    if not words:
        return None
    added: list[str] = col.get_config(_CFG_WORDS, []) or []
    today = date.today().isoformat()
    last_date = col.get_config(_CFG_DATE, "") or ""

    if not force and last_date == today:
        return None

    next_word = next((w for w in words if w["word"] not in added), None)
    if next_word is None:
        # Bank exhausted; still record that we checked today.
        col.set_config(_CFG_DATE, today)
        return None

    _add_vocab_card(col, next_word)
    added.append(next_word["word"])
    col.set_config(_CFG_WORDS, added)
    col.set_config(_CFG_DATE, today)
    return next_word


# --- score formatting for the home payload ---------------------------------


def _score_dict(score: Any, scaled: bool) -> dict[str, Any]:
    if score.available:
        if scaled:
            value = f"{score.estimate:.0f}"
            rng = f"{score.low:.0f}\u2013{score.high:.0f}"
        else:
            value = f"{score.estimate * 100:.0f}%"
            rng = f"{score.low * 100:.0f}%\u2013{score.high * 100:.0f}%"
    else:
        value = ""
        rng = ""
    return {
        "available": score.available,
        "value": value,
        "range": rng,
        "confidence": score.confidence,
        "sampleSize": score.sample_size,
        "reasons": list(score.reasons),
    }


def _fill_blank(stem: str, word: str) -> str:
    """Replace a fill-in-the-blank run of underscores with `word`."""
    filled = re.sub(r"_{2,}", word, stem)
    return filled if filled != stem else f"{stem} {word}."


def _word_entry(item: dict[str, Any], distractor: dict[str, Any] | None) -> dict[str, Any]:
    """A learned-word card plus a two-sentence 'which uses it correctly?' quiz.

    The correct sentence is the word's real example; the wrong sentence drops
    the word into a context that actually calls for a different word.
    """
    word = item["word"]
    correct = item.get("example", "") or _fill_blank(
        item.get("context_question", {}).get("stem", ""), word
    )
    wrong = ""
    if distractor:
        d_stem = distractor.get("context_question", {}).get("stem", "")
        if d_stem:
            wrong = _fill_blank(d_stem, word)
        elif distractor.get("example"):
            wrong = _fill_blank(
                distractor["example"].replace(distractor["word"], "______", 1), word
            )
    return {
        "word": word,
        "pos": item.get("part_of_speech", ""),
        "def": item["definition"],
        "example": item.get("example", ""),
        "quiz": {"word": word, "correct": correct, "wrong": wrong} if wrong else None,
    }


# Whether the user has already started a lesson/Socratic during this app run.
# The Home button uses this to reopen the expanded menu instead of the initial
# hub, so users don't have to re-tap the homebase every time. It resets on
# restart (module reload), so a fresh launch still starts on the hub.
_ENGAGED_THIS_RUN = False


def _mark_engaged() -> None:
    global _ENGAGED_THIS_RUN
    _ENGAGED_THIS_RUN = True


def _home_payload(mw: aqt.AnkiQt) -> dict[str, Any]:
    """Everything the home screen needs, delivered over the JS bridge."""
    col = mw.col
    res = col.lsat_readiness()

    added: list[str] = col.get_config(_CFG_WORDS, []) or []
    words = _load_vocab()
    by_name = {w["word"]: w for w in words}

    learned = [by_name[name] for name in added if name in by_name]
    word_entries = [
        _word_entry(item, words[(words.index(item) + 1) % len(words)] if words else None)
        for item in learned
    ]

    profile = _profile(col)

    return {
        "profile": profile,
        "plan": _plan(profile),
        "house": _house(col),
        "words": word_entries,
        "vocabCount": len(added),
        "vocabTotal": len(words),
        "loggedIn": bool(mw.pm.sync_auth()),
        "scores": {
            "memory": _score_dict(res.memory, scaled=False),
            "performance": _score_dict(res.performance, scaled=False),
            "readiness": _score_dict(res.readiness, scaled=True),
        },
        "gradedReviews": res.graded_reviews,
        "nextStep": res.next_best_step,
        "missing": list(res.missing_data),
        "startInMenu": _ENGAGED_THIS_RUN,
    }


# --- vocab review + sync actions -------------------------------------------


def _start_vocab_review(mw: aqt.AnkiQt) -> None:
    deck_id = mw.col.decks.id_for_name(VOCAB_DECK)
    if not deck_id:
        tooltip("No vocab yet — open the home screen to get your first word.")
        return
    mw.col.decks.select(deck_id)
    mw.moveToState("overview")


# --- LSAT home as the main window state ------------------------------------


class LsatHome:
    """Renders the Svelte `lsat-home` page as Anki's main landing screen."""

    def __init__(self, mw: aqt.AnkiQt) -> None:
        self.mw = mw
        self.web = mw.web
        self.bottom = BottomBar(mw, mw.bottomWeb)

    def show(self) -> None:
        av_player.stop_and_clear_queue()
        self.web.set_bridge_command(self._on_cmd, self)
        self.mw.toolbar.redraw()
        self.web.load_sveltekit_page("lsat-home")
        self.bottom.draw(buf="", link_handler=lambda *_: None, web_context=self)

    def _on_cmd(self, cmd: str) -> Any:
        mw = self.mw
        if cmd == "lsat:home":
            return _home_payload(mw)
        if cmd == "lsat:vocab:ensure":
            _ensure_word_of_the_day(mw.col)
            return _home_payload(mw)
        if cmd == "lsat:vocab:add":
            added = _ensure_word_of_the_day(mw.col, force=True)
            if added is None:
                tooltip("You've added every available word for now.")
            else:
                tooltip(f"Added \u201c{added['word']}\u201d to your vocab bank.")
            return _home_payload(mw)
        if cmd == "lsat:vocab:review":
            mw.moveToState("lsatReview")
            return True
        if cmd == "lsat:sync":
            mw.on_sync_button_clicked()
            return True
        if cmd == "lsat:onboard:questions":
            return {"questions": _diagnostic_questions()}
        if cmd.startswith("lsat:onboard:complete:"):
            payload = cmd[len("lsat:onboard:complete:") :]
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                data = {}
            _complete_onboarding(mw.col, data)
            return _home_payload(mw)
        if cmd == "lsat:lesson:start":
            _mark_engaged()
            mw.moveToState("lsatPractice", "lesson")
            return True
        if cmd == "lsat:socratic:open":
            _mark_engaged()
            mw.moveToState("lsatSocratic")
            return True
        if cmd.startswith("lsat:house:buy:"):
            upgrade_id = cmd.rsplit(":", 1)[-1]
            result = _buy_upgrade(mw.col, upgrade_id)
            if not result.get("ok") and result.get("reason") == "coins":
                tooltip("Not enough coins yet — earn more in a lesson or the Socratic Station.")
            return _home_payload(mw)
        if cmd.startswith("lsat:practice:"):
            parts = cmd.split(":")
            section = parts[2] if len(parts) > 2 else "lr"
            _mark_engaged()
            mw.moveToState("lsatPractice", section)
            return True
        if cmd == "lsat:decks":
            mw.moveToState("deckBrowser")
            return True
        return False


# --- interactive LR/RC practice (FSRS-tracked MCQ cards) -------------------

MCQ_NOTETYPE = "LSAT MCQ"
PRACTICE_DECKS = {
    "lr": "LSAT Practice::Logical Reasoning",
    "rc": "LSAT Practice::Reading Comprehension",
}
SECTION_LABELS = {"lr": "Logical Reasoning", "rc": "Reading Comprehension"}
_CFG_ATTEMPTS = "lsat:attempts"  # read by the Rust engine for the Performance score
_CFG_PRACTICE_IMPORTED = "lsat:practice_imported"
_CFG_PROFILE = "lsat:profile"
_CFG_PET = "lsat:pet"  # legacy pet config; coins are migrated to the house
_CFG_HOUSE = "lsat:house"
_LETTERS = ["A", "B", "C", "D", "E"]

# Adaptive lesson + study-plan parameters.
LESSON_SECONDS = 2 * 60 * 60  # a timed lesson runs 2 hours
PLAN_MONTHS = 8
DAILY_HOURS = 2

# Currency rewards.
COINS_PER_LESSON_CORRECT = 100
COINS_PER_SOCRATIC_CORRECT = 500

# Homebase upgrades: coins earned in lessons/Socratic are poured into the house.
# Each id maps to a visual layer on the floating-island house in the UI.
HOUSE_UPGRADES = [
    {"id": "garden", "name": "Greenery", "desc": "Shrubs and a little tree on your island.", "cost": 500},
    {"id": "hedges", "name": "Hedge border", "desc": "A trimmed hedge around the island rim.", "cost": 800},
    {"id": "orchard", "name": "Garden", "desc": "A real garden with fruit and vegetable beds.", "cost": 1000},
    {"id": "path", "name": "Stone path", "desc": "A tidy walkway out to the island edge.", "cost": 1200},
    {"id": "flag", "name": "Rooftop banner", "desc": "A maroon pennant flying from the peak.", "cost": 1500},
    {"id": "lights", "name": "Warm lights", "desc": "Shutters and a warm glow across the island.", "cost": 2000},
    {"id": "lamps", "name": "Lamp posts", "desc": "Lanterns lining both sides of the path.", "cost": 2800},
    {"id": "pond", "name": "Reflecting pond", "desc": "A calm little pond on the island.", "cost": 3500},
    {"id": "fountain", "name": "Fountain", "desc": "A bubbling stone fountain on the lawn.", "cost": 4500},
    {"id": "tower", "name": "Study tower", "desc": "A second story for late-night prep.", "cost": 6000},
    {"id": "balloon", "name": "Hot-air balloon", "desc": "A balloon drifting past your homebase.", "cost": 7500},
    {"id": "observatory", "name": "Observatory", "desc": "A rooftop dome to watch the stars.", "cost": 10000},
    {"id": "aurora", "name": "Sunset sky", "desc": "Bathe the sky in a purple-to-gold sunset.", "cost": 18000},
]


# The interactive MCQ lives in the *card template* (not just the desktop Svelte
# page) so the exact same synced cards are clickable/answerable on any Anki
# client that renders templates in a WebView -- notably AnkiDroid on the phone.
# The scheduling (FSRS), storage, and sync are all handled by the shared Rust
# engine; this template only adds the click-to-answer UX on top of it.
_MCQ_CSS = """
.card {
  font-family: Jost, "Segoe UI", system-ui, -apple-system, sans-serif;
  background: #f6edda;
  color: #2c1b1e;
  padding: 18px 16px;
  text-align: left;
  line-height: 1.5;
}
.lsat-stim {
  background: #fffdf6;
  border: 1px solid #ece0c2;
  border-radius: 10px;
  padding: 12px 14px;
  margin-bottom: 14px;
  font-size: 0.95em;
}
.lsat-q { font-weight: 700; color: #4a0d18; margin-bottom: 14px; }
.lsat-choices { display: flex; flex-direction: column; gap: 8px; }
.lsat-ch {
  text-align: left;
  padding: 11px 13px;
  border: 2px solid #ece0c2;
  border-radius: 10px;
  background: #fffdf6;
  color: #2c1b1e;
  font: inherit;
  cursor: pointer;
  width: 100%;
}
.lsat-ch.correct { border-color: #2f7d4f; background: #e2f0e6; }
.lsat-ch.wrong { border-color: #b23a3a; background: #f7e0e0; }
.lsat-let { color: #8c1c2b; font-weight: 700; margin-right: 6px; }
.lsat-expl {
  margin-top: 14px;
  padding: 12px 14px;
  border-left: 5px solid #6e1423;
  background: #ece0c2;
  border-radius: 8px;
  font-size: 0.95em;
}
.lsat-verdict { font-weight: 700; margin-bottom: 6px; }
.lsat-verdict.ok { color: #2f7d4f; }
.lsat-verdict.no { color: #b23a3a; }
"""

_MCQ_QFMT = """
<div class="lsat-card" data-answer="{{Answer}}">
  {{#Stimulus}}<div class="lsat-stim">{{Stimulus}}</div>{{/Stimulus}}
  <div class="lsat-q">{{Question}}</div>
  <div class="lsat-choices">
    {{#A}}<button class="lsat-ch" data-letter="A"><span class="lsat-let">A</span>{{A}}</button>{{/A}}
    {{#B}}<button class="lsat-ch" data-letter="B"><span class="lsat-let">B</span>{{B}}</button>{{/B}}
    {{#C}}<button class="lsat-ch" data-letter="C"><span class="lsat-let">C</span>{{C}}</button>{{/C}}
    {{#D}}<button class="lsat-ch" data-letter="D"><span class="lsat-let">D</span>{{D}}</button>{{/D}}
    {{#E}}<button class="lsat-ch" data-letter="E"><span class="lsat-let">E</span>{{E}}</button>{{/E}}
  </div>
  <div class="lsat-expl" id="lsatExpl" style="display:none">
    <div class="lsat-verdict" id="lsatVerdict"></div>
    <div>{{Explanation}}</div>
  </div>
</div>
<script>
(function(){
  var root = document.querySelector('.lsat-card');
  if(!root || root.dataset.wired) return;
  root.dataset.wired = '1';
  var ans = (root.getAttribute('data-answer')||'').trim().toUpperCase();
  var done = false;
  var btns = root.querySelectorAll('.lsat-ch');
  btns.forEach(function(b){
    b.addEventListener('click', function(){
      if(done) return; done = true;
      var pick = (b.getAttribute('data-letter')||'').toUpperCase();
      btns.forEach(function(x){
        var l = (x.getAttribute('data-letter')||'').toUpperCase();
        if(l === ans) x.classList.add('correct');
        else if(l === pick) x.classList.add('wrong');
      });
      var v = document.getElementById('lsatVerdict');
      if(pick === ans){ v.textContent = 'Correct'; v.className = 'lsat-verdict ok'; }
      else { v.textContent = 'Incorrect \\u2014 correct answer is ' + ans; v.className = 'lsat-verdict no'; }
      document.getElementById('lsatExpl').style.display = 'block';
    });
  });
})();
</script>
"""

_MCQ_AFMT = """
<div class="lsat-card">
  {{#Stimulus}}<div class="lsat-stim">{{Stimulus}}</div>{{/Stimulus}}
  <div class="lsat-q">{{Question}}</div>
  <div class="lsat-expl">
    <div class="lsat-verdict ok">Answer: {{Answer}}</div>
    <div>{{Explanation}}</div>
  </div>
</div>
"""


def _ensure_mcq_notetype(col: Collection) -> Any:
    m = col.models.by_name(MCQ_NOTETYPE)
    if m is None:
        m = col.models.new(MCQ_NOTETYPE)
        for fname in ["Stimulus", "Question", *_LETTERS, "Answer", "Explanation", "Section"]:
            col.models.add_field(m, col.models.new_field(fname))
        template = col.models.new_template("Card 1")
        template["qfmt"] = _MCQ_QFMT
        template["afmt"] = _MCQ_AFMT
        col.models.add_template(m, template)
        m["css"] = _MCQ_CSS
        col.models.add(m)
        return col.models.by_name(MCQ_NOTETYPE)

    # Refresh the template on existing collections so cards already created
    # (and already synced to the phone) pick up the interactive, mobile-ready
    # layout without a re-import.
    changed = False
    if m["tmpls"]:
        tmpl = m["tmpls"][0]
        if tmpl.get("qfmt") != _MCQ_QFMT or tmpl.get("afmt") != _MCQ_AFMT:
            tmpl["qfmt"] = _MCQ_QFMT
            tmpl["afmt"] = _MCQ_AFMT
            changed = True
    if m.get("css") != _MCQ_CSS:
        m["css"] = _MCQ_CSS
        changed = True
    if changed:
        col.models.update_dict(m)
    return col.models.by_name(MCQ_NOTETYPE)


def _add_mcq(
    col: Collection,
    notetype: Any,
    deck_name: str,
    *,
    stimulus: str,
    question: str,
    choices: dict[str, str],
    answer: str,
    explanation: str,
    section: str,
) -> None:
    deck_id = col.decks.id(deck_name)
    note = col.new_note(notetype)
    note["Stimulus"] = stimulus
    note["Question"] = question
    for letter in _LETTERS:
        note[letter] = choices.get(letter, "")
    note["Answer"] = answer.strip()
    note["Explanation"] = explanation
    note["Section"] = section
    note.tags = ["lsat", f"lsat::{section.lower().replace(' ', '_')}"]
    col.add_note(note, deck_id)


def ensure_practice_imported(col: Collection) -> None:
    """Import LR/RC questions as MCQ cards, incrementally and idempotently.

    Runs every launch. The notetype refresh keeps the mobile-ready template up
    to date, and any question in the bundled content that is not already in the
    collection is added -- so expanding the question bank simply shows up as new
    cards on the next launch, without duplicating existing ones.
    """
    notetype = _ensure_mcq_notetype(col)
    content_dir = _content_dir()
    if content_dir is None:
        return

    def key(stimulus: str, stem: str) -> str:
        # Stem alone is not unique (many passages share stems like "main point"),
        # so identity is stimulus + stem.
        return f"{(stimulus or '').strip()}\x1f{(stem or '').strip()}"

    # Existing questions, so re-imports don't create duplicates.
    existing: set[str] = set()
    for nid in col.find_notes(f'note:"{MCQ_NOTETYPE}"'):
        note = col.get_note(nid)
        try:
            existing.add(key(note["Stimulus"], note["Question"]))
        except KeyError:
            continue

    lr_path = content_dir / "logical_reasoning.json"
    if lr_path.exists():
        for item in json.loads(lr_path.read_text()).get("items", []):
            k = key(item.get("stimulus", ""), item["stem"])
            if k in existing:
                continue
            _add_mcq(
                col,
                notetype,
                PRACTICE_DECKS["lr"],
                stimulus=item["stimulus"],
                question=item["stem"],
                choices=item.get("choices", {}),
                answer=item["answer"],
                explanation=item.get("explanation", ""),
                section="Logical Reasoning",
            )
            existing.add(k)

    rc_path = content_dir / "reading_comprehension.json"
    if rc_path.exists():
        for passage in json.loads(rc_path.read_text()).get("items", []):
            ptext = passage["passage"]
            for q in passage.get("questions", []):
                k = key(ptext, q["stem"])
                if k in existing:
                    continue
                _add_mcq(
                    col,
                    notetype,
                    PRACTICE_DECKS["rc"],
                    stimulus=ptext,
                    question=q["stem"],
                    choices=q.get("choices", {}),
                    answer=q["answer"],
                    explanation=q.get("explanation", ""),
                    section="Reading Comprehension",
                )
                existing.add(k)

    col.set_config(_CFG_PRACTICE_IMPORTED, True)


def _record_attempt(col: Collection, *, section: str, correct: bool) -> None:
    attempts: list[dict[str, Any]] = col.get_config(_CFG_ATTEMPTS, []) or []
    attempts.append({"correct": correct, "section": section})
    col.set_config(_CFG_ATTEMPTS, attempts)


# --- onboarding profile + adaptive study plan ------------------------------


def _profile(col: Collection) -> dict[str, Any]:
    p = col.get_config(_CFG_PROFILE, None) or {}
    return {
        "onboarded": bool(p.get("onboarded")),
        "name": p.get("name", ""),
        "startDate": p.get("startDate", ""),
        "planMonths": p.get("planMonths", PLAN_MONTHS),
        "dailyHours": p.get("dailyHours", DAILY_HOURS),
        "diagnostic": p.get("diagnostic"),
    }


def _plan(profile: dict[str, Any]) -> dict[str, Any]:
    sd = profile.get("startDate") or date.today().isoformat()
    try:
        start = date.fromisoformat(sd)
    except ValueError:
        start = date.today()
    total_days = int(profile.get("planMonths", PLAN_MONTHS) * 30)
    end = start + timedelta(days=total_days)
    day_num = max(1, min((date.today() - start).days + 1, total_days))
    return {
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "dailyHours": profile.get("dailyHours", DAILY_HOURS),
        "totalDays": total_days,
        "dayNumber": day_num,
    }


def _mcq_from_item(item: dict[str, Any], section: str, stimulus: str) -> dict[str, Any]:
    return {
        "section": section,
        "sectionLabel": SECTION_LABELS[section],
        "stimulus": stimulus,
        "question": item["stem"],
        "choices": [
            {"letter": k, "text": v} for k, v in item.get("choices", {}).items()
        ],
        "answer": item["answer"],
        "explanation": item.get("explanation", ""),
    }


def _diagnostic_questions(limit_per_section: int = 3) -> list[dict[str, Any]]:
    """A short mixed set of graded questions to gauge a starting level."""
    content_dir = _content_dir()
    if content_dir is None:
        return []
    out: list[dict[str, Any]] = []
    lr_path = content_dir / "logical_reasoning.json"
    if lr_path.exists():
        for item in json.loads(lr_path.read_text()).get("items", [])[:limit_per_section]:
            out.append(_mcq_from_item(item, "lr", item.get("stimulus", "")))
    rc_path = content_dir / "reading_comprehension.json"
    if rc_path.exists():
        count = 0
        for passage in json.loads(rc_path.read_text()).get("items", []):
            for q in passage.get("questions", []):
                out.append(_mcq_from_item(q, "rc", passage["passage"]))
                count += 1
                if count >= limit_per_section:
                    break
            if count >= limit_per_section:
                break
    return out


def _complete_onboarding(col: Collection, data: dict[str, Any]) -> None:
    diagnostic = data.get("diagnostic") or {}
    profile = {
        "onboarded": True,
        "name": (data.get("name") or "").strip()[:60],
        "startDate": data.get("startDate") or date.today().isoformat(),
        "planMonths": PLAN_MONTHS,
        "dailyHours": DAILY_HOURS,
        "diagnostic": {
            "correct": int(diagnostic.get("correct", 0)),
            "total": int(diagnostic.get("total", 0)),
        },
    }
    col.set_config(_CFG_PROFILE, profile)
    # Diagnostic answers are genuine graded questions -> feed the honest score.
    for a in diagnostic.get("answers", []):
        _record_attempt(
            col, section=a.get("section", "lr"), correct=bool(a.get("correct"))
        )


def _section_stats(col: Collection) -> dict[str, list[int]]:
    stats = {"lr": [0, 0], "rc": [0, 0]}
    for a in col.get_config(_CFG_ATTEMPTS, []) or []:
        s = a.get("section")
        if s in stats:
            stats[s][1] += 1
            if a.get("correct"):
                stats[s][0] += 1
    return stats


def _weakest_first(col: Collection) -> list[str]:
    """Section order for adaptive lessons: weakest (or untested) first."""
    stats = _section_stats(col)

    def accuracy(section: str) -> float:
        correct, total = stats[section]
        return (correct / total) if total else -1.0  # untested -> highest priority

    return sorted(["lr", "rc"], key=accuracy)


# --- currency + homebase ---------------------------------------------------


def _house(col: Collection) -> dict[str, Any]:
    h = col.get_config(_CFG_HOUSE, None) or {}
    coins = h.get("coins")
    if coins is None:
        # First run after the pet was retired: carry over any earned coins.
        legacy = col.get_config(_CFG_PET, None) or {}
        coins = int(legacy.get("coins", 0))
    owned = list(h.get("upgrades", []))
    catalog = [{**u, "owned": u["id"] in owned} for u in HOUSE_UPGRADES]
    return {"coins": int(coins), "upgrades": owned, "catalog": catalog}


def _save_house(col: Collection, coins: int, upgrades: list[str]) -> None:
    col.set_config(_CFG_HOUSE, {"coins": int(coins), "upgrades": list(upgrades)})


def _add_coins(col: Collection, amount: int) -> None:
    if amount <= 0:
        return
    h = _house(col)
    _save_house(col, h["coins"] + amount, h["upgrades"])


def _buy_upgrade(col: Collection, upgrade_id: str) -> dict[str, Any]:
    h = _house(col)
    spec = next((u for u in HOUSE_UPGRADES if u["id"] == upgrade_id), None)
    if spec is None:
        return {"ok": False}
    if upgrade_id in h["upgrades"]:
        return {"ok": True}
    if h["coins"] < spec["cost"]:
        return {"ok": False, "reason": "coins"}
    _save_house(col, h["coins"] - spec["cost"], h["upgrades"] + [upgrade_id])
    return {"ok": True}


class LsatPractice:
    """Interactive MCQ practice rendered by the Svelte `lsat-practice` page.

    Cards are real Anki notes graded through the FSRS scheduler (so memory and
    mastery are tracked exactly like normal study), but the learner answers by
    clicking a choice and getting immediate feedback instead of flipping.
    """

    def __init__(self, mw: aqt.AnkiQt) -> None:
        self.mw = mw
        self.web = mw.web
        self.bottom = BottomBar(mw, mw.bottomWeb)
        self.mode = "lesson"  # "lesson" (adaptive + timed) or "lr"/"rc"
        self.lesson_start: float | None = None
        self.lesson_active = False
        self.correct = 0
        self.total = 0
        self._current: tuple[int, Any, str, str] | None = None

    def show(self, section: str = "lesson") -> None:
        self.mode = section if section in ("lesson", "lr", "rc") else "lesson"
        ensure_practice_imported(self.mw.col)
        if self.mode == "lesson":
            # Don't auto-start the lesson on entry — the intro/hourglass animation
            # runs first and the clock starts when the user presses "Begin". If a
            # lesson is already running we keep its clock + score so toggling back
            # from the home screen resumes exactly where the user left off. Only a
            # lesson whose 2 hours have elapsed gets cleared (so the intro shows
            # again for a fresh run).
            expired = (
                self.lesson_start is not None
                and (time.time() - self.lesson_start) >= LESSON_SECONDS
            )
            if expired:
                self.lesson_start = None
                self.lesson_active = False
                self.correct = 0
                self.total = 0
        else:
            self.lesson_start = None
            self.lesson_active = False
            self.correct = 0
            self.total = 0
        av_player.stop_and_clear_queue()
        self.web.set_bridge_command(self._on_cmd, self)
        self.mw.toolbar.redraw()
        self.web.load_sveltekit_page("lsat-practice")
        self.bottom.draw(buf="", link_handler=lambda *_: None, web_context=self)

    def _remaining_seconds(self) -> int | None:
        if self.mode != "lesson" or self.lesson_start is None:
            return None
        return max(0, int(LESSON_SECONDS - (time.time() - self.lesson_start)))

    def _pull_from(self, section: str) -> Any | None:
        col = self.mw.col
        col.decks.select(col.decks.id(PRACTICE_DECKS[section]))
        queued = col.sched.get_queued_cards(fetch_limit=1)
        return queued if queued.cards else None

    def _next_card(self) -> dict[str, Any]:
        col = self.mw.col
        remaining_time = self._remaining_seconds()

        progress = {"correct": self.correct, "total": self.total}
        if self.mode == "lesson":
            session = {"total": LESSON_SECONDS, "remaining": remaining_time}
            if remaining_time is not None and remaining_time <= 0:
                self._current = None
                self.lesson_active = False
                return {
                    "done": True,
                    "reason": "time",
                    "session": session,
                    "progress": progress,
                }
            order = _weakest_first(col)
        else:
            session = None
            order = [self.mode]

        queued = section = None
        for sec in order:
            q = self._pull_from(sec)
            if q is not None:
                queued, section = q, sec
                break

        if queued is None:
            self._current = None
            return {
                "done": True,
                "reason": "empty",
                "session": session,
                "progress": progress,
            }

        qc = queued.cards[0]
        card = col.get_card(qc.card.id)
        card.start_timer()
        note = card.note()
        answer = note["Answer"].strip()
        self._current = (card.id, qc.states, answer, section)
        choices = [
            {"letter": letter, "text": note[letter]}
            for letter in _LETTERS
            if note[letter].strip()
        ]
        remaining = queued.new_count + queued.learning_count + queued.review_count
        return {
            "done": False,
            "section": SECTION_LABELS[section],
            "stimulus": note["Stimulus"],
            "question": note["Question"],
            "choices": choices,
            "answer": answer,
            "explanation": note["Explanation"],
            "remaining": remaining,
            "session": session,
            "progress": progress,
        }

    def _answer(self, letter: str) -> dict[str, Any]:
        from anki.scheduler.v3 import CardAnswer

        if not self._current:
            return {"ok": False}
        card_id, states, answer_letter, section = self._current
        correct = letter.upper() == answer_letter.upper()
        col = self.mw.col
        _record_attempt(col, section=section, correct=correct)
        self.total += 1
        coins = 0
        if correct:
            self.correct += 1
            coins = COINS_PER_LESSON_CORRECT
            _add_coins(col, coins)
        card = col.get_card(card_id)
        card.start_timer()
        rating = CardAnswer.GOOD if correct else CardAnswer.AGAIN
        built = col.sched.build_answer(card=card, states=states, rating=rating)
        col.sched.answer_card(built)
        # The review is now recorded honestly for FSRS. Bury the card so the
        # lesson always advances to a *new* question instead of repeating this
        # one moments later (a wrong answer would otherwise re-enter the learning
        # queue and reappear within the session). It returns on schedule next day.
        try:
            col.sched.bury_cards([card_id], manual=False)
        except TypeError:
            col.sched.bury_cards([card_id])
        self._current = None
        return {"ok": True, "correct": correct, "coins": coins}

    def _on_cmd(self, cmd: str) -> Any:
        if cmd == "lsat:practice:resume":
            # Called on page load. If a lesson is already running, hand back the
            # next card so the UI can skip the intro animation and restore the
            # clock + score. Otherwise report inactive so the intro plays.
            if self.mode == "lesson" and self.lesson_active:
                payload = self._next_card()
                payload["active"] = True
                return payload
            return {"active": False}
        if cmd == "lsat:practice:begin":
            # The user pressed "Begin" on the intro screen: (re)start the clock
            # here so the countdown reflects the moment they actually started.
            if self.mode == "lesson":
                self.lesson_start = time.time()
                self.lesson_active = True
                self.correct = 0
                self.total = 0
            return self._next_card()
        if cmd == "lsat:practice:next":
            return self._next_card()
        if cmd.startswith("lsat:practice:answer:"):
            return self._answer(cmd.rsplit(":", 1)[-1])
        if cmd == "lsat:practice:exit":
            self.mw.moveToState("lsatHome")
            return True
        return False


# --- Socratic Station (explain why a wrong answer is wrong) -----------------

_STOPWORDS = set(
    "the a an of to in is are was were be been being and or but if then that this "
    "these those it its as for on with by from at into than about which who whom "
    "whose what why how not no nor so too very can will just does did doing they "
    "them their there here your you i we he she his her our because also would "
    "could should more most some any each other one two answer choice question".split()
)


def _significant_words(text: str) -> set[str]:
    words = re.findall(r"[a-zA-Z']+", (text or "").lower())
    return {w for w in words if len(w) > 3 and w not in _STOPWORDS}


def _socratic_pool() -> list[dict[str, Any]]:
    content_dir = _content_dir()
    if content_dir is None:
        return []
    pool: list[dict[str, Any]] = []
    lr_path = content_dir / "logical_reasoning.json"
    if lr_path.exists():
        for item in json.loads(lr_path.read_text()).get("items", []):
            pool.append(
                {
                    "stimulus": item["stimulus"],
                    "question": item["stem"],
                    "choices": item.get("choices", {}),
                    "answer": item["answer"],
                    "explanation": item.get("explanation", ""),
                }
            )
    rc_path = content_dir / "reading_comprehension.json"
    if rc_path.exists():
        for passage in json.loads(rc_path.read_text()).get("items", []):
            for q in passage.get("questions", []):
                pool.append(
                    {
                        "stimulus": passage["passage"],
                        "question": q["stem"],
                        "choices": q.get("choices", {}),
                        "answer": q["answer"],
                        "explanation": q.get("explanation", ""),
                    }
                )
    return pool


class LsatSocratic:
    """Socratic Station: the app names a *wrong* answer and asks the learner to
    articulate precisely why it fails. A keyword heuristic stands in for the
    (not-yet-permitted) AI grader; a correct explanation earns coins.
    """

    def __init__(self, mw: aqt.AnkiQt) -> None:
        self.mw = mw
        self.web = mw.web
        self.bottom = BottomBar(mw, mw.bottomWeb)
        self.pool: list[dict[str, Any]] = []
        self._current: dict[str, Any] | None = None

    def show(self) -> None:
        self.pool = _socratic_pool()
        av_player.stop_and_clear_queue()
        self.web.set_bridge_command(self._on_cmd, self)
        self.mw.toolbar.redraw()
        self.web.load_sveltekit_page("lsat-socratic")
        self.bottom.draw(buf="", link_handler=lambda *_: None, web_context=self)

    def _next(self) -> dict[str, Any]:
        import random

        if not self.pool:
            return {"done": True}
        q = random.choice(self.pool)
        wrong = [
            k
            for k, v in q["choices"].items()
            if k.upper() != q["answer"].upper() and v.strip()
        ]
        if not wrong:
            return {"done": True}
        letter = random.choice(wrong)
        self._current = q
        return {
            "done": False,
            "stimulus": q["stimulus"],
            "question": q["question"],
            "choices": [
                {"letter": k, "text": v}
                for k, v in q["choices"].items()
                if v.strip()
            ],
            "wrongLetter": letter,
            "correctAnswer": q["answer"],
        }

    def _judge(self, text: str) -> dict[str, Any]:
        if not self._current:
            return {"ok": False}
        q = self._current
        keywords = _significant_words(q["explanation"])
        overlap = len(keywords & _significant_words(text))
        word_count = len(re.findall(r"[a-zA-Z']+", text or ""))
        correct = overlap >= 2 and word_count >= 6
        coins = 0
        if correct:
            coins = COINS_PER_SOCRATIC_CORRECT
            _add_coins(self.mw.col, coins)
        return {
            "correct": correct,
            "coins": coins,
            "explanation": q["explanation"],
        }

    def _on_cmd(self, cmd: str) -> Any:
        if cmd == "lsat:socratic:next":
            return self._next()
        if cmd.startswith("lsat:socratic:submit:"):
            return self._judge(cmd[len("lsat:socratic:submit:") :])
        if cmd == "lsat:socratic:exit":
            self.mw.moveToState("lsatHome")
            return True
        return False


# --- themed vocab flashcard review (matches the home UI) -------------------


def _vocab_note_data(note: Any, by_name: dict[str, Any]) -> dict[str, Any]:
    """Clean word/def/example from a note, regardless of note type.

    New cards use the `LSAT Vocab` note type; older ones use `Basic`. Either
    way we resolve to clean text (looking up bundled content when possible).
    """
    try:
        word = note["Word"]
    except KeyError:
        word = None
    if word is not None:
        return {
            "word": note["Word"],
            "pos": note["PartOfSpeech"],
            "def": note["Definition"],
            "example": note["Example"],
        }
    raw = note.fields[0] if note.fields else ""
    word_txt = re.sub(r"<[^>]+>", "", raw).strip()
    meta = by_name.get(word_txt)
    if meta:
        return {
            "word": word_txt,
            "pos": meta.get("part_of_speech", ""),
            "def": meta["definition"],
            "example": meta.get("example", ""),
        }
    back = re.sub(r"<[^>]+>", " ", note.fields[1] if len(note.fields) > 1 else "")
    return {"word": word_txt, "pos": "", "def": back.strip(), "example": ""}


class LsatVocabReview:
    """Vocab flashcards reviewed in the app's own maroon/beige UI.

    Uses the FSRS scheduler over the bridge (so memory/mastery are tracked
    exactly like normal study), but rendered by the Svelte `lsat-review` page
    so it matches the home screen instead of Anki's default reviewer.
    """

    def __init__(self, mw: aqt.AnkiQt) -> None:
        self.mw = mw
        self.web = mw.web
        self.bottom = BottomBar(mw, mw.bottomWeb)
        self._current: tuple[int, Any] | None = None

    def show(self) -> None:
        deck_id = self.mw.col.decks.id(VOCAB_DECK)
        self.mw.col.decks.select(deck_id)
        av_player.stop_and_clear_queue()
        self.web.set_bridge_command(self._on_cmd, self)
        self.mw.toolbar.redraw()
        self.web.load_sveltekit_page("lsat-review")
        self.bottom.draw(buf="", link_handler=lambda *_: None, web_context=self)

    def _next_card(self) -> dict[str, Any]:
        col = self.mw.col
        queued = col.sched.get_queued_cards(fetch_limit=1)
        if not queued.cards:
            self._current = None
            return {"done": True}
        qc = queued.cards[0]
        card = col.get_card(qc.card.id)
        card.start_timer()
        self._current = (card.id, qc.states)
        by_name = {w["word"]: w for w in _load_vocab()}
        data = _vocab_note_data(card.note(), by_name)
        data["done"] = False
        data["remaining"] = (
            queued.new_count + queued.learning_count + queued.review_count
        )
        return data

    def _answer(self, rating_name: str) -> dict[str, Any]:
        from anki.scheduler.v3 import CardAnswer

        if not self._current:
            return {"ok": False}
        card_id, states = self._current
        col = self.mw.col
        card = col.get_card(card_id)
        card.start_timer()
        rmap = {
            "again": CardAnswer.AGAIN,
            "hard": CardAnswer.HARD,
            "good": CardAnswer.GOOD,
            "easy": CardAnswer.EASY,
        }
        rating = rmap.get(rating_name, CardAnswer.GOOD)
        built = col.sched.build_answer(card=card, states=states, rating=rating)
        col.sched.answer_card(built)
        self._current = None
        return {"ok": True}

    def _on_cmd(self, cmd: str) -> Any:
        if cmd == "lsat:review:next":
            return self._next_card()
        if cmd.startswith("lsat:review:answer:"):
            return self._answer(cmd.rsplit(":", 1)[-1])
        if cmd == "lsat:review:exit":
            self.mw.moveToState("lsatHome")
            return True
        return False


# --- legacy readiness dialog (kept for the menu) ---------------------------


def _format_score(name: str, score: Any, scaled: bool) -> str:
    if score.available:
        if scaled:
            estimate = f"{score.estimate:.0f}"
            rng = f"{score.low:.0f}\u2013{score.high:.0f}"
        else:
            estimate = f"{score.estimate * 100:.0f}%"
            rng = f"{score.low * 100:.0f}%\u2013{score.high * 100:.0f}%"
        reasons = "<br>".join(html.escape(r) for r in score.reasons)
        return (
            f"<h3>{name}: {estimate}</h3>"
            f"<p>Likely range: <b>{rng}</b> &nbsp;|&nbsp; "
            f"confidence: {score.confidence * 100:.0f}% &nbsp;|&nbsp; "
            f"based on {score.sample_size} data point(s)</p>"
            f"<p style='color:#666'>{reasons}</p>"
        )
    reasons = "<br>".join(html.escape(r) for r in score.reasons)
    return f"<h3>{name}: not enough data yet</h3><p style='color:#666'>{reasons}</p>"


def _readiness_html(res: Any) -> str:
    parts = [
        "<h2>LSAT Readiness</h2>",
        _format_score("Memory", res.memory, scaled=False),
        _format_score("Performance", res.performance, scaled=False),
        _format_score("Readiness (120\u2013180)", res.readiness, scaled=True),
        "<hr>",
        f"<p><b>Graded reviews so far:</b> {res.graded_reviews}</p>",
        f"<p><b>Next best step:</b> {html.escape(res.next_best_step)}</p>",
    ]
    return "".join(parts)


class ReadinessDialog(QDialog):
    def __init__(self, mw: aqt.AnkiQt, res: Any) -> None:
        super().__init__(mw)
        self.setWindowTitle("LSAT Readiness")
        self.resize(540, 600)
        layout = QVBoxLayout(self)
        browser = QTextBrowser(self)
        browser.setHtml(_readiness_html(res))
        layout.addWidget(browser)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        qconnect(buttons.rejected, self.reject)
        qconnect(buttons.accepted, self.accept)
        layout.addWidget(buttons)


def show_readiness(mw: aqt.AnkiQt) -> None:
    QueryOp(
        parent=mw,
        op=lambda col: col.lsat_readiness(),
        success=lambda res: ReadinessDialog(mw, res).show(),
    ).run_in_background()


def import_lsat_content(mw: aqt.AnkiQt) -> None:
    """Legacy menu action: seed the whole vocab bank at once."""
    words = _load_vocab()
    if not words:
        showWarning("No LSAT vocabulary content found.")
        return

    def op(col: Collection) -> int:
        added: list[str] = col.get_config(_CFG_WORDS, []) or []
        count = 0
        for w in words:
            if w["word"] in added:
                continue
            _add_vocab_card(col, w)
            added.append(w["word"])
            count += 1
        col.set_config(_CFG_WORDS, added)
        col.set_config(_CFG_DATE, date.today().isoformat())
        return count

    def run() -> None:
        n = op(mw.col)
        tooltip(f"Seeded {n} vocab card(s) into '{VOCAB_DECK}'.")
        if mw.state == "lsatHome":
            mw.moveToState("lsatHome")

    run()
