import type { Segment } from "@/api/types";

export interface TranscriptTurn {
  id: string;
  speaker_label: string;
  start_seconds: number;
  end_seconds: number;
  text: string;
  segments: Segment[];
}

/** Reading groups only: source segment IDs, text, timing and edits stay intact. */
export function groupTranscriptTurns(segments: readonly Segment[], maxPauseSeconds = 2): TranscriptTurn[] {
  const turns: TranscriptTurn[] = [];
  const valid = (s: Segment) => Number.isFinite(s.start_seconds) && Number.isFinite(s.end_seconds)
    && s.start_seconds >= 0 && s.end_seconds > s.start_seconds;

  for (const segment of segments) {
    const previous = turns[turns.length - 1];
    const last = previous?.segments[previous.segments.length - 1];
    const gap = last ? segment.start_seconds - last.end_seconds : Infinity;
    if (previous && last && segment.speaker_label === last.speaker_label
      && segment.sequence === last.sequence + 1 && !segment.is_overlap && !last.is_overlap
      && valid(segment) && valid(last) && gap >= 0 && gap <= maxPauseSeconds + 1e-6) {
      previous.segments.push(segment);
      previous.end_seconds = segment.end_seconds;
      previous.text += " " + (segment.edited_text ?? segment.original_text);
    } else {
      turns.push({
        id: segment.id, speaker_label: segment.speaker_label,
        start_seconds: segment.start_seconds, end_seconds: segment.end_seconds,
        text: segment.edited_text ?? segment.original_text, segments: [segment],
      });
    }
  }
  return turns;
}
