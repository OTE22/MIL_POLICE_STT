"""Evaluate held-out identification scores without changing operational thresholds.

Input JSON: a list of {probe_id, expected_identity (null for unknown), candidates:
[{identity_id, score, source_recording_id}], probe_recording_id}.
Scores must come from compatible model/provider/revision embeddings. Use different
recordings for gallery and probes. Multiple prints collapse to the best per person.
"""
import argparse
import json
import math
from pathlib import Path


def evaluate(rows, threshold, margin):
    counts = dict(probes=0, known=0, unknown=0, correct=0, wrong_identity=0,
                  false_accept_unknown=0, rejected_known=0, rejected_unknown=0)
    seen = set()
    for row in rows:
        if row['probe_id'] in seen:
            raise ValueError('Duplicate probe_id')
        seen.add(row['probe_id'])
        if not row.get('probe_recording_id'):
            raise ValueError('Each probe must identify its recording')
        scores = {}
        for candidate in row['candidates']:
            if not candidate.get('source_recording_id') or candidate['source_recording_id'] == row['probe_recording_id']:
                raise ValueError('Gallery and probe recordings must be distinct and identified')
            score = float(candidate['score'])
            if not math.isfinite(score) or not -1 <= score <= 1:
                raise ValueError('Cosine scores must be finite and between -1 and 1')
            person = candidate['identity_id']
            scores[person] = max(scores.get(person, -1.0), score)
        ranking = sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))
        accepted = bool(ranking and ranking[0][1] >= threshold and
                        (len(ranking) == 1 or ranking[0][1] - ranking[1][1] >= margin))
        expected = row['expected_identity']
        known = expected is not None
        counts['probes'] += 1
        counts['known' if known else 'unknown'] += 1
        if not accepted:
            counts['rejected_known' if known else 'rejected_unknown'] += 1
        elif not known:
            counts['false_accept_unknown'] += 1
        elif ranking[0][0] == expected:
            counts['correct'] += 1
        else:
            counts['wrong_identity'] += 1
    return dict(threshold=threshold, margin=margin, **counts,
                unknown_false_accept_rate=counts['false_accept_unknown'] / counts['unknown'] if counts['unknown'] else None,
                known_rejection_rate=counts['rejected_known'] / counts['known'] if counts['known'] else None,
                known_wrong_identity_rate=counts['wrong_identity'] / counts['known'] if counts['known'] else None)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--thresholds', type=float, nargs='+', default=[0.65, 0.7, 0.75, 0.8])
    parser.add_argument('--margin', type=float, default=0.05)
    args = parser.parse_args()
    rows = json.loads(args.input.read_text(encoding='utf-8'))
    if not rows or not any(r['expected_identity'] is None for r in rows) or not any(r['expected_identity'] is not None for r in rows):
        parser.error('Supply both known and unknown held-out speakers')
    if not 0 <= args.margin <= 2 or any(not -1 <= t <= 1 for t in args.thresholds):
        parser.error('Invalid threshold or margin')
    print(json.dumps([evaluate(rows, t, args.margin) for t in args.thresholds], indent=2))
