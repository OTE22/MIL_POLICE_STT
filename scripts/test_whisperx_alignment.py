import json
import unittest
from evaluate_whisperx_alignment import attribute_words, report_json, split_runs, valid_interval


def turn(speaker, start, end):
    return {"speaker_label": speaker, "start_seconds": start, "end_seconds": end}


class AutomaticAttributionTests(unittest.TestCase):
    def test_splits_at_speaker_change_without_losing_words(self):
        words = [{"word": text, "start": a, "end": b}
                 for text, a, b in [("مرحبا", 0.1, 0.8), ("أهلا", 1.1, 1.8), ("بك", 1.9, 2.4)]]
        result = split_runs(attribute_words(words, [turn("A", 0, 1), turn("B", 1, 3)]))
        self.assertEqual([r["speaker_label"] for r in result], ["A", "B"])
        self.assertEqual([r["text"] for r in result], ["مرحبا", "أهلا بك"])
        self.assertEqual(result[1]["start_seconds"], 1.1)

    def test_missing_time_and_silence_are_not_forced_to_nearest_speaker(self):
        result = attribute_words([{"word": "untimed"}, {"word": "gap", "start": 2, "end": 3}], [turn("A", 0, 1)])
        self.assertEqual([w["speaker"] for w in result], [None, None])
        self.assertEqual([w["attribution_status"] for w in result], ["unaligned", "outside_speaker_turns"])
        self.assertEqual(len(split_runs(result)), 2)

    def test_simultaneous_voices_remain_ambiguous(self):
        words = attribute_words([{"word": "both", "start": 1, "end": 2}], [turn("A", 0, 3), turn("B", 1, 2)])
        self.assertIsNone(words[0]["speaker"])
        self.assertTrue(words[0]["is_overlap"])
        self.assertEqual(words[0]["attribution_status"], "ambiguous")

    def test_boundary_crossing_is_not_simultaneous_speech(self):
        words = attribute_words([{"word": "boundary", "start": 0.8, "end": 1.5}], [turn("A", 0, 1), turn("B", 1, 2)])
        self.assertEqual(words[0]["speaker"], "B")
        self.assertFalse(words[0]["is_overlap"])

    def test_duplicate_turns_do_not_bias_assignment(self):
        words = attribute_words([{"word": "test", "start": 0, "end": 1}],
                                [turn("A", 0, 0.4), turn("A", 0, 0.4), turn("B", 0.4, 1)])
        self.assertEqual(words[0]["speaker"], "B")

    def test_nan_and_invalid_turns_are_rejected(self):
        word = attribute_words([{"word": "test", "start": float("nan"), "end": 1}], [turn("A", 0, 1)])[0]
        self.assertIsNone(word["start"])
        with self.assertRaises(ValueError):
            attribute_words([], [turn("A", 2, 1)])

    def test_numpy_alignment_output_exports_as_json_numbers(self):
        import numpy as np

        words = attribute_words([
            {"word": "مرحبا", "start": np.float64(0.1), "end": np.float64(0.8),
             "score": np.float32(0.75)}
        ], [turn("A", 0, 1)])
        timed = valid_interval(words[0]["start"], words[0]["end"])
        self.assertIs(type(timed), bool)
        report = {"timed_words": np.int64(sum([timed])), "valid": np.bool_(True),
                  "segments": split_runs(words)}
        decoded = json.loads(report_json(report))
        self.assertEqual(decoded["timed_words"], 1)
        self.assertIs(type(decoded["timed_words"]), int)
        self.assertIs(decoded["valid"], True)
        self.assertEqual(decoded["segments"][0]["words"][0]["score"], 0.75)
        self.assertEqual(decoded["segments"][0]["text"], "مرحبا")

    def test_report_export_rejects_nonfinite_numbers_and_unknown_objects(self):
        import numpy as np

        for value in (np.float32("nan"), np.float64("inf")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                report_json({"score": value})
        with self.assertRaises(TypeError):
            report_json({"unexpected": object()})


if __name__ == "__main__":
    unittest.main()
