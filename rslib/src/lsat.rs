// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

//! LSAT Speedrun: the three honest scores, computed inside Anki's Rust engine.
//!
//! - **Memory**: average current FSRS recall probability across reviewed cards,
//!   with a 95% confidence interval for the mean.
//! - **Performance**: the memory -> new-question bridge. Not enabled before the
//!   Friday (AI) milestone, so it honestly reports "unavailable" instead of
//!   inventing a number.
//! - **Readiness**: the performance -> projected-score bridge. Enforces the
//!   give-up rule (PRD §8.2): no score until there is enough graded data *and* a
//!   working performance model.
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

/// Give-up rule for readiness: minimum graded reviews before a readiness score
/// can be shown (mirrors PRD §8.2).
pub(crate) const MIN_GRADED_REVIEWS_FOR_READINESS: usize = 200;

/// One graded practice answer, as persisted in the collection config.
#[derive(Debug, Clone, Deserialize)]
struct Attempt {
    #[serde(default)]
    correct: bool,
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

/// Readiness (performance -> projected LSAT score). Enforces the give-up rule:
/// no score until there is enough graded data AND a working performance model.
fn readiness_score(graded_reviews: usize, performance_available: bool) -> LsatScore {
    let mut reasons = Vec::new();
    if graded_reviews < MIN_GRADED_REVIEWS_FOR_READINESS {
        reasons.push(format!(
            "Not enough data: need at least {MIN_GRADED_REVIEWS_FOR_READINESS} graded reviews, \
             have {graded_reviews}."
        ));
    }
    if !performance_available {
        reasons.push(
            "A validated performance model is required before a readiness score can be shown."
                .to_string(),
        );
    }
    // Readiness is never fabricated in this milestone; it stays hidden until the
    // performance model exists and the data threshold is met.
    unavailable(reasons, graded_reviews)
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

    /// Correctness of each recorded graded practice attempt.
    fn lsat_attempts(&self) -> Vec<bool> {
        let attempts: Vec<Attempt> = self
            .get_config_optional(ATTEMPTS_CONFIG_KEY)
            .unwrap_or_default();
        attempts.into_iter().map(|a| a.correct).collect()
    }

    /// Compute the three honest LSAT scores.
    pub fn lsat_readiness(&mut self) -> Result<ReadinessResponse> {
        let retrievabilities = self.lsat_retrievabilities()?;
        let graded_reviews = self.lsat_graded_reviews()?;
        let attempts = self.lsat_attempts();

        let memory = memory_score(&retrievabilities);
        let performance = performance_score(&attempts);
        let readiness = readiness_score(attempts.len(), performance.available);

        let mut missing_data = Vec::new();
        if !memory.available {
            missing_data
                .push("More reviewed cards are needed to establish a memory baseline.".to_string());
        }
        if !performance.available {
            missing_data.push(
                "A validated performance model (exam-style questions) is not built yet.".to_string(),
            );
        }
        if attempts.len() < MIN_GRADED_REVIEWS_FOR_READINESS {
            missing_data.push(format!(
                "{} more graded practice questions needed before a readiness score.",
                MIN_GRADED_REVIEWS_FOR_READINESS.saturating_sub(attempts.len())
            ));
        }

        let next_best_step = if !memory.available {
            "Review more LSAT cards to build a memory baseline.".to_string()
        } else if !readiness.available {
            "Keep practicing graded questions — readiness unlocks once there is enough data and a \
             performance model."
                .to_string()
        } else {
            "Focus on your weakest question type.".to_string()
        };

        Ok(ReadinessResponse {
            memory: Some(memory),
            performance: Some(performance),
            readiness: Some(readiness),
            graded_reviews: graded_reviews as u32,
            topic_coverage: 0.0,
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

    #[test]
    fn readiness_refuses_until_threshold_and_model() {
        // Not enough reviews and no performance model -> two reasons, hidden.
        let score = readiness_score(10, false);
        assert!(!score.available);
        assert_eq!(score.reasons.len(), 2);
        // Enough reviews but still no performance model -> still hidden.
        let score = readiness_score(MIN_GRADED_REVIEWS_FOR_READINESS + 1, false);
        assert!(!score.available);
        assert_eq!(score.reasons.len(), 1);
    }
}
