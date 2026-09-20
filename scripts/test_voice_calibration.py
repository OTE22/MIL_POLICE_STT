import unittest
from evaluate_voice_thresholds import evaluate


class CalibrationTests(unittest.TestCase):
    def row(self, key, expected, scores):
        return dict(probe_id=key, expected_identity=expected, probe_recording_id='held-out',
                    candidates=[dict(identity_id=person, score=score, source_recording_id='gallery')
                                for person, score in scores])

    def test_distinguishes_unknown_acceptance_wrong_person_and_rejection(self):
        rows = [self.row('1', 'A', [('A', .9), ('A', .88), ('B', .5)]),
                self.row('2', None, [('A', .8)]),
                self.row('3', 'B', [('A', .9), ('B', .7)]),
                self.row('4', 'A', [('A', .8), ('B', .79)]),
                self.row('5', None, [('A', .4)])]
        result = evaluate(rows, .65, .05)
        for key in ['correct', 'false_accept_unknown', 'wrong_identity', 'rejected_known', 'rejected_unknown']:
            self.assertEqual(result[key], 1)
        self.assertEqual(result['unknown_false_accept_rate'], .5)

    def test_rejects_training_recording_leakage(self):
        row = self.row('1', 'A', [('A', 1.)])
        row['probe_recording_id'] = 'gallery'
        with self.assertRaises(ValueError):
            evaluate([row], .65, .05)


if __name__ == '__main__':
    unittest.main()
