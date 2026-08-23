"""Speaker-turn post-processing and STT window construction.

Pipeline (pure functions, fully unit-testable):

 1. clean        - clip turns to the audio, drop invalid / empty ones
 2. trim_to_vad  - intersect each turn with VAD speech regions (no silence to STT)
 3. drop_tiny    - discard fragments shorter than `min_turn_seconds`
 4. merge        - consolidate consecutive SAME-speaker fragments separated by a
                   short gap. NEVER merges across a different speaker: if any other
                   speaker starts talking inside the gap the fragments stay separate.
 5. split_long   - split segments longer than `max_seconds` at the widest VAD
                   silence inside them (hard split as last resort) so that the
                   STT model always gets bounded, context-rich windows
 6. windows      - add `context_padding` seconds before/after each segment for
                   linguistic context. Padding is CLAMPED to the previous / next
                   segment boundary (any speaker) so two windows never cover the
                   same audio -> no duplicate transcription between neighbours.
                   Overlapping speech (two speakers at once) is the one intentional
                   exception: both speakers' segments cover the shared audio and are
                   flagged `is_overlap`, because hiding one voice would misattribute
                   speech.

Speaker attribution (who) comes exclusively from diarization; the text (what)
comes exclusively from STT. This module only decides the audio windows.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.ai.types import SpeakerTurn, SpeechRegion


@dataclass
class SegmentPlan:
    speaker_label: str
    start_seconds: float
    end_seconds: float
    is_overlap: bool
    window_start: float
    window_end: float


@dataclass
class SegmentSettings:
    min_turn_seconds: float = 0.3
    merge_gap_seconds: float = 0.7
    max_seconds: float = 28.0
    context_padding_seconds: float = 0.3


def clean(turns: list[SpeakerTurn], duration: float) -> list[SpeakerTurn]:
    out = []
    for t in turns:
        start = max(0.0, t.start_seconds)
        end = min(duration, t.end_seconds) if duration > 0 else t.end_seconds
        if end - start <= 0:
            continue
        out.append(SpeakerTurn(t.speaker_label, round(start, 3), round(end, 3), t.is_overlap))
    out.sort(key=lambda t: (t.start_seconds, t.end_seconds))
    return out


def trim_to_vad(turns: list[SpeakerTurn], speech: list[SpeechRegion]) -> list[SpeakerTurn]:
    if not speech:
        return []
    out = []
    for t in turns:
        for r in speech:
            if r.end_seconds <= t.start_seconds:
                continue
            if r.start_seconds >= t.end_seconds:
                break
            s = max(t.start_seconds, r.start_seconds)
            e = min(t.end_seconds, r.end_seconds)
            if e > s:
                out.append(SpeakerTurn(t.speaker_label, round(s, 3), round(e, 3), t.is_overlap))
    out.sort(key=lambda t: (t.start_seconds, t.end_seconds))
    return out


def drop_tiny(turns: list[SpeakerTurn], min_turn_seconds: float) -> list[SpeakerTurn]:
    kept = [t for t in turns if t.duration >= min_turn_seconds]
    # Never return nothing if there was speech: keep the longest fragment instead.
    if not kept and turns:
        kept = [max(turns, key=lambda t: t.duration)]
    return kept


def _other_speaker_in_gap(turns: list[SpeakerTurn], a: SpeakerTurn, b: SpeakerTurn) -> bool:
    for t in turns:
        if t.speaker_label == a.speaker_label:
            continue
        if t.start_seconds >= a.end_seconds - 1e-6 and t.start_seconds <= b.start_seconds + 1e-6:
            return True
        # A turn of another speaker spanning the gap also blocks the merge.
        if t.start_seconds < a.end_seconds and t.end_seconds > b.start_seconds:
            return True
    return False


def merge(turns: list[SpeakerTurn], gap: float, max_seconds: float) -> list[SpeakerTurn]:
    out: list[SpeakerTurn] = []
    by_speaker_last: dict[str, SpeakerTurn] = {}
    for t in turns:
        prev = by_speaker_last.get(t.speaker_label)
        if (
            prev is not None
            and 0 <= t.start_seconds - prev.end_seconds <= gap
            and (t.end_seconds - prev.start_seconds) <= max_seconds
            and not _other_speaker_in_gap(turns, prev, t)
        ):
            prev.end_seconds = max(prev.end_seconds, t.end_seconds)
            prev.is_overlap = prev.is_overlap or t.is_overlap
            continue
        nt = SpeakerTurn(t.speaker_label, t.start_seconds, t.end_seconds, t.is_overlap)
        out.append(nt)
        by_speaker_last[t.speaker_label] = nt
    out.sort(key=lambda t: (t.start_seconds, t.end_seconds))
    return out


def _silences_between(speech: list[SpeechRegion], start: float, end: float) -> list[tuple[float, float]]:
    gaps = []
    prev_end = start
    for r in speech:
        if r.end_seconds <= start:
            continue
        if r.start_seconds >= end:
            break
        if r.start_seconds > prev_end:
            gaps.append((prev_end, r.start_seconds))
        prev_end = max(prev_end, r.end_seconds)
    return [(s, e) for s, e in gaps if start < s < end]


def split_long(turns: list[SpeakerTurn], speech: list[SpeechRegion], max_seconds: float) -> list[SpeakerTurn]:
    out: list[SpeakerTurn] = []
    stack = list(turns)
    while stack:
        t = stack.pop(0)
        if t.duration <= max_seconds:
            out.append(t)
            continue
        # Prefer splitting at the widest silence inside the first max_seconds.
        limit = t.start_seconds + max_seconds
        candidates = [
            g for g in _silences_between(speech, t.start_seconds + 1.0, limit) if g[0] > t.start_seconds + 1.0
        ]
        if candidates:
            gs, ge = max(candidates, key=lambda g: g[1] - g[0])
            cut_a, cut_b = gs, ge
        else:
            cut_a = cut_b = limit
        first = SpeakerTurn(t.speaker_label, t.start_seconds, round(cut_a, 3), t.is_overlap)
        rest = SpeakerTurn(t.speaker_label, round(cut_b, 3), t.end_seconds, t.is_overlap)
        out.append(first)
        if rest.duration > 0.05:
            stack.insert(0, rest)
    out.sort(key=lambda t: (t.start_seconds, t.end_seconds))
    return out


def build_windows(turns: list[SpeakerTurn], duration: float, padding: float) -> list[SegmentPlan]:
    plans: list[SegmentPlan] = []
    for i, t in enumerate(turns):
        ws = max(0.0, t.start_seconds - padding)
        we = min(duration, t.end_seconds + padding) if duration > 0 else t.end_seconds + padding
        # Clamp to neighbours (any speaker): each side may use at most half of the
        # gap to its neighbour, so two windows never share audio.
        for other in turns[:i][::-1]:
            if other.end_seconds <= t.start_seconds:
                half = other.end_seconds + (t.start_seconds - other.end_seconds) / 2.0
                ws = max(ws, half)
                break
        for other in turns[i + 1 :]:
            if other.start_seconds >= t.end_seconds:
                half = t.end_seconds + (other.start_seconds - t.end_seconds) / 2.0
                we = min(we, half)
                break
        plans.append(
            SegmentPlan(
                speaker_label=t.speaker_label,
                start_seconds=t.start_seconds,
                end_seconds=t.end_seconds,
                is_overlap=t.is_overlap,
                window_start=round(min(ws, t.start_seconds), 3),
                window_end=round(max(we, t.end_seconds), 3),
            )
        )
    return plans


def plan_segments(
    turns: list[SpeakerTurn],
    speech: list[SpeechRegion],
    duration: float,
    settings: SegmentSettings,
    *,
    vad_enabled: bool = True,
) -> list[SegmentPlan]:
    turns = clean(turns, duration)
    if vad_enabled:
        turns = trim_to_vad(turns, speech)
    turns = drop_tiny(turns, settings.min_turn_seconds)
    turns = merge(turns, settings.merge_gap_seconds, settings.max_seconds)
    turns = split_long(turns, speech if vad_enabled else [], settings.max_seconds)
    return build_windows(turns, duration, settings.context_padding_seconds)
