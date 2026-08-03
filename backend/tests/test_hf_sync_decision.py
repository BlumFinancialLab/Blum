from __future__ import annotations

import unittest

from scripts.hf_sync_decision import classify_sync


class HuggingFaceSyncDecisionTests(unittest.TestCase):
    def test_equal_revisions_are_noop(self) -> None:
        self.assertEqual(classify_sync("a", "a", True, True), "noop_equal")

    def test_hf_behind_is_noop(self) -> None:
        self.assertEqual(classify_sync("b", "a", False, True), "noop_hf_behind")

    def test_hf_ahead_fast_forwards(self) -> None:
        self.assertEqual(classify_sync("a", "b", True, False), "fast_forward")

    def test_divergence_requires_pull_request(self) -> None:
        self.assertEqual(classify_sync("a", "b", False, False), "pull_request")

    def test_empty_revision_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "commit SHA"):
            classify_sync("", "b", False, False)


if __name__ == "__main__":
    unittest.main()
