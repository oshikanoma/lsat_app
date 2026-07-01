# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""End-to-end test for the LSAT Speedrun scoring service.

Exercises the new Rust engine change (`LsatService.GetReadiness`) all the way
through the protobuf layer from Python, and verifies the honesty / give-up rule.
"""

from tests.shared import getEmptyCol


def test_lsat_readiness_give_up_rule():
    col = getEmptyCol()

    res = col.lsat_readiness()

    # A fresh collection has no reviews, so every score must refuse to show a
    # number rather than inventing one.
    assert res.memory.available is False
    assert res.performance.available is False
    assert res.readiness.available is False
    assert res.graded_reviews == 0

    # The hidden scores must explain *why* they are hidden (the honesty rule).
    assert res.memory.reasons
    assert res.readiness.reasons
    assert res.missing_data
    assert res.next_best_step

    # Adding cards without reviewing them does not unlock the memory score,
    # because none of them have FSRS memory state yet.
    notetype = col.models.by_name("Basic")
    deck_id = col.decks.id("LSAT")
    for i in range(15):
        note = col.new_note(notetype)
        note.fields[0] = f"Question {i}"
        note.fields[1] = f"Answer {i}"
        col.add_note(note, deck_id)

    res2 = col.lsat_readiness()
    assert res2.memory.available is False
    assert res2.readiness.available is False
