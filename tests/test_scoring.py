from __future__ import annotations

import unittest

from campus_job_ranker.scoring import CRITERIA, DIMENSION_WEIGHTS, score_signals
from tests.helpers import signals


class ScoringTests(unittest.TestCase):
    def test_weights_total_one_hundred(self) -> None:
        self.assertEqual(sum(DIMENSION_WEIGHTS.values()), 100.0)
        self.assertEqual(sum(item.points for item in CRITERIA.values()), 100.0)

    def test_all_strong_scores_one_hundred(self) -> None:
        score = score_signals(signals("strong"))
        self.assertEqual(score.conservative_score, 100.0)
        self.assertEqual(score.theoretical_upper, 100.0)
        self.assertEqual(score.coverage, 1.0)

    def test_partial_scores_half(self) -> None:
        score = score_signals(signals("partial"))
        self.assertEqual(score.conservative_score, 50.0)
        self.assertEqual(score.theoretical_upper, 50.0)
        self.assertEqual(score.coverage, 1.0)

    def test_unknown_only_affects_theoretical_upper(self) -> None:
        score = score_signals(signals("unknown"))
        self.assertEqual(score.conservative_score, 0.0)
        self.assertEqual(score.theoretical_upper, 100.0)
        self.assertEqual(score.coverage, 0.0)


if __name__ == "__main__":
    unittest.main()
