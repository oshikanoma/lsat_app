// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

//! LSAT Speedrun: the three honest scores, computed inside Anki's Rust engine.
//!
//! - **Memory**: average current FSRS recall probability across reviewed cards,
//!   with a 95% confidence interval for the mean.
//! - **Performance**: how accurately the learner answers graded LR/RC practice
//!   questions, with a 95% confidence interval. Hidden until there are enough
//!   graded questions to be meaningful.
//! - **Readiness**: the performance -> projected-score bridge (120–180). Enforces
//!   the give-up rule (PRD §8.2): shows NO score until ALL of the following hold
//!   — at least [`MIN_GRADED_PRACTICE_FOR_READINESS`] graded practice questions,
//!   at least [`MIN_LR_COVERAGE_FOR_READINESS`] of the LR question-type taxonomy
//!   covered, at least [`MIN_RC_PASSAGES_FOR_READINESS`] completed RC passages,
//!   and a working performance model. Until then it reports exactly what is
//!   missing. Once unlocked it projects performance accuracy onto the 120–180
//!   scale with a range.
//!
//! Exposed to every client (desktop + mobile) through the shared backend, so the
//! same engine drives both apps.

use fsrs::FSRS;
use fsrs::FSRS5_DEFAULT_DECAY;
use serde::Deserialize;

use anki_proto::lsat::GetReadinessRequest;
use anki_proto::lsat::LsatScore;
use anki_proto::lsat::ReadinessResponse;

use crate::collection::Collection;
use crate::prelude::*;
use crate::search::SearchNode;

/// Config key holding the log of graded practice attempts (written by the
/// desktop/mobile practice flow). Each entry records whether the answer was
/// correct, so the engine can compute an honest Performance score.
pub(crate) const ATTEMPTS_CONFIG_KEY: &str = "lsat:attempts";

/// Minimum number of reviewed (FSRS-tracked) cards before we will report a
/// memory score. Below this we refuse to guess.
pub(crate) const MIN_MEMORY_CARDS: usize = 10;

/// Minimum number of graded practice questions before we will report a
/// performance score. Below this we refuse to guess.
pub(crate) const MIN_ATTEMPTS_FOR_PERFORMANCE: usize = 20;

/// Give-up rule (PRD §8.2), part 1: minimum graded practice questions across the
/// two scored sections before a readiness score can be shown.
pub(crate) const MIN_GRADED_PRACTICE_FOR_READINESS: usize = 200;

/// Give-up rule (PRD §8.2), part 2: minimum fraction of the LR question-type
/// taxonomy the learner must have attempted (0..1).
pub(crate) const MIN_LR_COVERAGE_FOR_READINESS: f32 = 0.50;

/// Give-up rule (PRD §8.2), part 3: minimum number of distinct completed RC
/// passages.
pub(crate) const MIN_RC_PASSAGES_FOR_READINESS: usize = 3;

/// The exam's Logical Reasoning question-type taxonomy. Readiness coverage is
/// measured as the fraction of these types the learner has actually attempted.
/// Compared case-insensitively against each attempt's `question_type`, so the
/// content bank's labels ("Weaken", "Necessary Assumption", "Resolve/Explain", …)
/// map straight onto it.
pub(crate) const LR_TAXONOMY: [&str; 14] = [
    "main point",
    "necessary assumption",
    "sufficient assumption",
    "strengthen",
    "weaken",
    "flaw",
    "inference",
    "method of reasoning",
    "parallel reasoning",
    "parallel flaw",
    "principle",
    "resolve/explain",
    "point at issue",
    "role in argument",
];

/// One graded practice answer, as persisted in the collection config by the
/// desktop/mobile practice flow. Older entries only carry `correct`; the
/// section/type/passage fields were added to drive the readiness coverage rules
/// and default to `None` when absent.
#[derive(Debug, Clone, Deserialize)]
struct Attempt {
    #[serde(default)]
    correct: bool,
    /// "lr" or "rc" (section the question belongs to).
    #[serde(default)]
    section: Option<String>,
    /// LR question type, e.g. "Weaken" (used for taxonomy coverage).
    #[serde(default)]
    question_type: Option<String>,
    /// Stable identifier of the RC passage (used to count distinct passages).
    #[serde(default)]
    passage: Option<String>,
}

fn unavailable(reasons: Vec<String>, sample_size: usize) -> LsatScore {
    LsatScore {
        available: false,
        estimate: 0.0,
        low: 0.0,
        high: 0.0,
        confidence: 0.0,
        sample_size: sample_size as u32,
        reasons,
    }
}

/// Summarise per-card retrievabilities into an honest memory score with a 95%
/// confidence interval for the mean. Pure function so it can be unit-tested
/// without a collection.
fn memory_score(retrievabilities: &[f32]) -> LsatScore {
    let n = retrievabilities.len();
    if n < MIN_MEMORY_CARDS {
        return unavailable(
            vec![format!(
                "Not enough data: need at least {MIN_MEMORY_CARDS} reviewed cards to estimate \
                 memory, but only {n} have FSRS history."
            )],
            n,
        );
    }
    let mean = retrievabilities.iter().sum::<f32>() / n as f32;
    let variance = retrievabilities
        .iter()
        .map(|r| (r - mean).powi(2))
        .sum::<f32>()
        / n as f32;
    let std_err = (variance / n as f32).sqrt();
    let margin = 1.96 * std_err;
    let low = (mean - margin).clamp(0.0, 1.0);
    let high = (mean + margin).clamp(0.0, 1.0);
    // Confidence grows with sample size, capped at 1.0 by 100 cards.
    let confidence = (n as f32 / 100.0).min(1.0);
    LsatScore {
        available: true,
        estimate: mean as f64,
        low: low as f64,
        high: high as f64,
        confidence: confidence as f64,
        sample_size: n as u32,
        reasons: vec![
            format!("Average current FSRS recall probability across {n} reviewed card(s)."),
            format!(
                "Likely range is a 95% confidence interval for the mean ({:.0}%–{:.0}%).",
                low * 100.0,
                high * 100.0
            ),
        ],
    }
}

/// Performance: how accurately the learner answers graded LSAT practice
/// questions. Computed from the recorded attempts, with a 95% confidence
/// interval for the true accuracy. Refuses to score below the data threshold.
/// Pure function so it can be unit-tested without a collection.
fn performance_score(attempts: &[bool]) -> LsatScore {
    let n = attempts.len();
    if n < MIN_ATTEMPTS_FOR_PERFORMANCE {
        return unavailable(
            vec![format!(
                "Not enough graded questions yet: need at least {MIN_ATTEMPTS_FOR_PERFORMANCE} \
                 answered practice questions, have {n}."
            )],
            n,
        );
    }
    let correct = attempts.iter().filter(|c| **c).count();
    let p = correct as f32 / n as f32;
    // Normal approximation to the binomial confidence interval for accuracy.
    let std_err = (p * (1.0 - p) / n as f32).sqrt();
    let margin = 1.96 * std_err;
    let low = (p - margin).clamp(0.0, 1.0);
    let high = (p + margin).clamp(0.0, 1.0);
    let confidence = (n as f32 / 100.0).min(1.0);
    LsatScore {
        available: true,
        estimate: p as f64,
        low: low as f64,
        high: high as f64,
        confidence: confidence as f64,
        sample_size: n as u32,
        reasons: vec![
            format!("Accuracy across {n} graded practice question(s): {correct} correct."),
            format!(
                "Likely range is a 95% confidence interval for accuracy ({:.0}%–{:.0}%).",
                low * 100.0,
                high * 100.0
            ),
        ],
    }
}

/// Coverage of the readiness give-up rule, derived from the graded attempts.
struct Coverage {
    /// Number of graded practice questions answered.
    graded_practice: usize,
    /// Distinct LR question types attempted, over the taxonomy size (0..1).
    lr_coverage: f32,
    /// Distinct completed RC passages.
    rc_passages: usize,
}

fn coverage_from_attempts(attempts: &[Attempt]) -> Coverage {
    use std::collections::HashSet;
    let taxonomy: HashSet<&str> = LR_TAXONOMY.iter().copied().collect();
    let mut lr_types: HashSet<String> = HashSet::new();
    let mut rc_passages: HashSet<String> = HashSet::new();
    for a in attempts {
        if let Some(qt) = &a.question_type {
            let norm = qt.trim().to_lowercase();
            if taxonomy.contains(norm.as_str()) {
                lr_types.insert(norm);
            }
        }
        let is_rc = a
            .section
            .as_deref()
            .map(|s| s.trim().to_lowercase().starts_with("rc"))
            .unwrap_or(false);
        if is_rc {
            if let Some(p) = &a.passage {
                if !p.trim().is_empty() {
                    rc_passages.insert(p.trim().to_string());
                }
            }
        }
    }
    Coverage {
        graded_practice: attempts.len(),
        lr_coverage: lr_types.len() as f32 / LR_TAXONOMY.len() as f32,
        rc_passages: rc_passages.len(),
    }
}

/// Readiness (performance -> projected LSAT score, 120–180). Enforces the full
/// three-part give-up rule (PRD §8.2) plus a working performance model; only
/// once every condition is met does it project a score with a range. Pure
/// function so the rule is unit-testable without a collection.
fn readiness_score(coverage: &Coverage, performance: &LsatScore) -> LsatScore {
    let Coverage {
        graded_practice,
        lr_coverage,
        rc_passages,
    } = *coverage;

    let mut reasons = Vec::new();
    if graded_practice < MIN_GRADED_PRACTICE_FOR_READINESS {
        reasons.push(format!(
            "Need at least {MIN_GRADED_PRACTICE_FOR_READINESS} graded practice questions across LR \
             + RC; have {graded_practice}."
        ));
    }
    if lr_coverage < MIN_LR_COVERAGE_FOR_READINESS {
        reasons.push(format!(
            "Need to cover at least {:.0}% of the LR question-type taxonomy; currently at {:.0}%.",
            MIN_LR_COVERAGE_FOR_READINESS * 100.0,
            lr_coverage * 100.0
        ));
    }
    if rc_passages < MIN_RC_PASSAGES_FOR_READINESS {
        reasons.push(format!(
            "Need at least {MIN_RC_PASSAGES_FOR_READINESS} completed RC passages; have \
             {rc_passages}."
        ));
    }
    if !performance.available {
        reasons.push(
            "A validated performance model is required before a readiness score can be shown."
                .to_string(),
        );
    }

    if !reasons.is_empty() {
        // A system that knows when it doesn't know: stay hidden and say why.
        return unavailable(reasons, graded_practice);
    }

    // Give-up rule satisfied. Project graded accuracy linearly onto the real
    // LSAT scale (120–180), carrying the performance interval through the same
    // map so the range stays honest.
    let scale = |accuracy: f64| 120.0 + accuracy.clamp(0.0, 1.0) * 60.0;
    let estimate = scale(performance.estimate);
    let low = scale(performance.low);
    let high = scale(performance.high);
    LsatScore {
        available: true,
        estimate,
        low,
        high,
        confidence: performance.confidence,
        sample_size: graded_practice as u32,
        reasons: vec![
            format!(
                "Projected from {:.0}% graded accuracy over {graded_practice} questions, mapped \
                 onto the 120–180 scale.",
                performance.estimate * 100.0
            ),
            format!("Likely range is {low:.0}–{high:.0} (from the performance interval)."),
        ],
    }
}

impl Collection {
    /// Current FSRS retrievability for every card that has memory state.
    fn lsat_retrievabilities(&mut self) -> Result<Vec<f32>> {
        let timing = self.timing_today()?;
        let cards = self.all_cards_for_search(SearchNode::WholeCollection)?;
        let fsrs = FSRS::new(None).unwrap();
        let mut out = Vec::new();
        for card in &cards {
            if let Some(state) = card.memory_state {
                let elapsed = card.seconds_since_last_review(&timing).unwrap_or_default();
                let r = fsrs.current_retrievability_seconds(
                    state.into(),
                    elapsed,
                    card.decay.unwrap_or(FSRS5_DEFAULT_DECAY),
                );
                out.push(r);
            }
        }
        Ok(out)
    }

    /// Number of genuine graded answers (buttons 1-4) in the review log.
    fn lsat_graded_reviews(&self) -> Result<usize> {
        Ok(self
            .storage
            .get_all_revlog_entries(TimestampSecs(0))?
            .iter()
            .filter(|e| (1..=4).contains(&e.button_chosen))
            .count())
    }

    /// All recorded graded practice attempts (correctness + coverage metadata).
    fn lsat_attempts(&self) -> Vec<Attempt> {
        self.get_config_optional(ATTEMPTS_CONFIG_KEY)
            .unwrap_or_default()
    }

    /// Compute the three honest LSAT scores.
    pub fn lsat_readiness(&mut self) -> Result<ReadinessResponse> {
        let retrievabilities = self.lsat_retrievabilities()?;
        let graded_reviews = self.lsat_graded_reviews()?;
        let attempts = self.lsat_attempts();
        let outcomes: Vec<bool> = attempts.iter().map(|a| a.correct).collect();
        let coverage = coverage_from_attempts(&attempts);

        let memory = memory_score(&retrievabilities);
        let performance = performance_score(&outcomes);
        let readiness = readiness_score(&coverage, &performance);

        let mut missing_data = Vec::new();
        if !memory.available {
            missing_data
                .push("More reviewed cards are needed to establish a memory baseline.".to_string());
        }
        if coverage.graded_practice < MIN_GRADED_PRACTICE_FOR_READINESS {
            missing_data.push(format!(
                "{} more graded practice questions needed.",
                MIN_GRADED_PRACTICE_FOR_READINESS.saturating_sub(coverage.graded_practice)
            ));
        }
        if coverage.lr_coverage < MIN_LR_COVERAGE_FOR_READINESS {
            missing_data.push(format!(
                "LR taxonomy coverage is {:.0}% — reach {:.0}% by practicing more question types.",
                coverage.lr_coverage * 100.0,
                MIN_LR_COVERAGE_FOR_READINESS * 100.0
            ));
        }
        if coverage.rc_passages < MIN_RC_PASSAGES_FOR_READINESS {
            missing_data.push(format!(
                "{} more RC passage(s) needed.",
                MIN_RC_PASSAGES_FOR_READINESS.saturating_sub(coverage.rc_passages)
            ));
        }

        let next_best_step = if !memory.available {
            "Review more LSAT cards to build a memory baseline.".to_string()
        } else if coverage.rc_passages < MIN_RC_PASSAGES_FOR_READINESS {
            "Complete a timed Reading Comprehension passage.".to_string()
        } else if coverage.lr_coverage < MIN_LR_COVERAGE_FOR_READINESS {
            "Practice an LR question type you haven't tried yet.".to_string()
        } else if !readiness.available {
            "Keep practicing graded questions — readiness unlocks once there is enough data."
                .to_string()
        } else {
            "Focus on your weakest question type.".to_string()
        };

        Ok(ReadinessResponse {
            memory: Some(memory),
            performance: Some(performance),
            readiness: Some(readiness),
            graded_reviews: graded_reviews as u32,
            // "% of the exam's question-type taxonomy covered so far" (PRD §8.1).
            topic_coverage: coverage.lr_coverage.min(1.0) as f64,
            last_updated: TimestampSecs::now().0,
            next_best_step,
            missing_data,
        })
    }
}

impl crate::services::LsatService for Collection {
    fn get_readiness(&mut self, _input: GetReadinessRequest) -> Result<ReadinessResponse> {
        self.lsat_readiness()
    }
}

#[cfg(test)]
mod test {
    use super::*;

    #[test]
    fn memory_score_refuses_without_enough_data() {
        // Below the threshold -> must refuse to score (give-up rule).
        let few = vec![0.9_f32; MIN_MEMORY_CARDS - 1];
        let score = memory_score(&few);
        assert!(!score.available);
        assert_eq!(score.estimate, 0.0);
        assert!(!score.reasons.is_empty());
    }

    #[test]
    fn memory_score_reports_honest_range() {
        // Enough data -> available, with low <= estimate <= high and a valid
        // confidence in [0, 1].
        let rs = vec![0.8_f32; MIN_MEMORY_CARDS + 5];
        let score = memory_score(&rs);
        assert!(score.available);
        assert!((score.estimate - 0.8).abs() < 1e-4);
        assert!(score.low <= score.estimate);
        assert!(score.estimate <= score.high);
        assert!((0.0..=1.0).contains(&score.confidence));
        assert_eq!(score.sample_size as usize, rs.len());
    }

    #[test]
    fn wider_spread_gives_wider_range() {
        // A noisier set of recall probabilities should yield a wider range.
        let tight = vec![0.5_f32; 50];
        let mut spread = vec![0.0_f32; 25];
        spread.extend(vec![1.0_f32; 25]);
        let tight_width = {
            let s = memory_score(&tight);
            s.high - s.low
        };
        let spread_width = {
            let s = memory_score(&spread);
            s.high - s.low
        };
        assert!(spread_width > tight_width);
    }

    #[test]
    fn performance_refuses_then_reports_accuracy() {
        // Below the threshold -> refuse to score.
        let few = vec![true; MIN_ATTEMPTS_FOR_PERFORMANCE - 1];
        assert!(!performance_score(&few).available);

        // Enough data -> available accuracy with an honest range.
        let mut attempts = vec![true; 30];
        attempts.extend(vec![false; 10]); // 30/40 correct = 75%
        let score = performance_score(&attempts);
        assert!(score.available);
        assert!((score.estimate - 0.75).abs() < 1e-4);
        assert!(score.low <= score.estimate && score.estimate <= score.high);
        assert_eq!(score.sample_size, 40);
    }

    /// Build a batch of graded attempts: `n` questions, `correct` of them right,
    /// spread across `lr_types` distinct LR types and `rc_passages` RC passages.
    fn attempts(n: usize, correct: usize, lr_types: usize, rc_passages: usize) -> Vec<Attempt> {
        let mut out = Vec::new();
        for i in 0..n {
            let (section, question_type, passage) = if i < rc_passages {
                // One question per distinct RC passage.
                (Some("rc".to_string()), None, Some(format!("passage-{i}")))
            } else {
                let qt = LR_TAXONOMY[i % lr_types.max(1)].to_string();
                (Some("lr".to_string()), Some(qt), None)
            };
            out.push(Attempt {
                correct: i < correct,
                section,
                question_type,
                passage,
            });
        }
        out
    }

    #[test]
    fn coverage_counts_distinct_types_and_passages() {
        let cov = coverage_from_attempts(&attempts(40, 40, 4, 3));
        assert_eq!(cov.graded_practice, 40);
        assert_eq!(cov.rc_passages, 3);
        // 4 distinct LR types out of the taxonomy.
        assert!((cov.lr_coverage - 4.0 / LR_TAXONOMY.len() as f32).abs() < 1e-6);
    }

    #[test]
    fn readiness_lists_each_unmet_condition() {
        // Well below every threshold, no performance model -> all four reasons.
        let cov = coverage_from_attempts(&attempts(5, 5, 1, 0));
        let perf = performance_score(&[true; 5]); // unavailable (< threshold)
        let score = readiness_score(&cov, &perf);
        assert!(!score.available);
        assert_eq!(score.reasons.len(), 4);
    }

    #[test]
    fn readiness_hidden_until_coverage_met() {
        // Enough questions + performance model, but zero RC passages and only
        // one LR type -> still hidden on the two coverage rules.
        let cov = coverage_from_attempts(&attempts(
            MIN_GRADED_PRACTICE_FOR_READINESS,
            MIN_GRADED_PRACTICE_FOR_READINESS,
            1,
            0,
        ));
        let perf = performance_score(&vec![true; MIN_GRADED_PRACTICE_FOR_READINESS]);
        assert!(perf.available);
        let score = readiness_score(&cov, &perf);
        assert!(!score.available);
        assert_eq!(score.reasons.len(), 2); // LR coverage + RC passages
    }

    #[test]
    fn readiness_scoring_latency_is_low() {
        // Measures the real backend scoring latency end to end (config load +
        // coverage + the three score computations) on a seeded collection, and
        // guards against regressions. Run with `--nocapture` to print the number.
        use std::time::Instant;

        let mut col = Collection::new();
        let mut attempts = Vec::new();
        for i in 0..500 {
            attempts.push(serde_json::json!({
                "correct": i % 3 != 0,
                "section": if i % 4 == 0 { "rc" } else { "lr" },
                "question_type": LR_TAXONOMY[i % LR_TAXONOMY.len()],
                "passage": format!("passage-{}", i % 6),
            }));
        }
        col.set_config_json(ATTEMPTS_CONFIG_KEY, &attempts, false)
            .unwrap();

        // Warm once, then time a batch.
        let _ = col.lsat_readiness().unwrap();
        let iters = 50u32;
        let start = Instant::now();
        for _ in 0..iters {
            let _ = col.lsat_readiness().unwrap();
        }
        let per = start.elapsed() / iters;
        eprintln!("lsat_readiness avg latency over {iters} runs: {per:?}");
        assert!(
            per.as_millis() < 100,
            "readiness scoring unexpectedly slow: {per:?}"
        );
    }

    #[test]
    fn readiness_unlocks_and_projects_120_180() {
        // All three give-up conditions satisfied, ~75% accuracy.
        let n = MIN_GRADED_PRACTICE_FOR_READINESS;
        let correct = n * 3 / 4;
        let cov = coverage_from_attempts(&attempts(n, correct, LR_TAXONOMY.len(), 5));
        assert!(cov.lr_coverage >= MIN_LR_COVERAGE_FOR_READINESS);
        assert!(cov.rc_passages >= MIN_RC_PASSAGES_FOR_READINESS);
        let mut outcomes = vec![true; correct];
        outcomes.extend(vec![false; n - correct]);
        let perf = performance_score(&outcomes);
        let score = readiness_score(&cov, &perf);
        assert!(score.available);
        // Projection stays on the real LSAT scale, with an honest ordered range.
        assert!(score.estimate >= 120.0 && score.estimate <= 180.0);
        assert!(score.low <= score.estimate && score.estimate <= score.high);
        assert!(score.high <= 180.0 && score.low >= 120.0);
    }
}
