import { strict as assert } from "node:assert";
import { test } from "node:test";
import type { Segment } from "../src/api/types.ts";
import { groupTranscriptTurns } from "../src/lib/transcript-turns.ts";
import { formatTimestamp } from "../src/lib/format.ts";

const segment = (sequence: number, label: string, start: number, end: number, extra: Partial<Segment> = {}): Segment => ({
  id: `segment-${sequence}`, sequence, speaker_label: label, start_seconds: start, end_seconds: end,
  original_text: `نص ${sequence}`, edited_text: null, confidence: null, is_overlap: false,
  edited_by: null, edited_by_name: null, edited_at: null, ...extra,
});

test("reported eight fragments become four turns, keeping every original segment", () => {
  const source = Object.freeze([
    segment(0, "SPEAKER_34", 1.84, 9.6), segment(1, "SPEAKER_34", 10.3, 12.73),
    segment(2, "SPEAKER_35", 13.1, 16.56), segment(3, "SPEAKER_34", 18.15, 20.87),
    segment(4, "SPEAKER_34", 21.64, 22.55), segment(5, "SPEAKER_34", 23.4, 28.73),
    segment(6, "SPEAKER_35", 29.5, 31.13), segment(7, "SPEAKER_35", 31.88, 32.64),
  ].map(s => Object.freeze(s)));
  const before = JSON.stringify(source);
  const turns = groupTranscriptTurns(source);
  assert.deepEqual(turns.map(t => t.speaker_label), ["SPEAKER_34", "SPEAKER_35", "SPEAKER_34", "SPEAKER_35"]);
  assert.deepEqual(turns.map(t => [t.start_seconds, t.end_seconds]), [[1.84, 12.73], [13.1, 16.56], [18.15, 28.73], [29.5, 32.64]]);
  assert.deepEqual(turns.map(t => t.segments.length), [2, 1, 3, 2]);
  assert.deepEqual(turns.flatMap(t => t.segments), source);
  assert.equal(turns[0].segments[1], source[1]);
  assert.equal(JSON.stringify(source), before);
});

test("filtering a speaker preserves interruptions by another voice", () => {
  const turns = groupTranscriptTurns([segment(0, "A", 0, 1), segment(1, "B", 1, 2), segment(2, "A", 2, 3)]);
  assert.equal(turns.filter(t => t.speaker_label === "A").length, 2);
});

test("long pauses and missing source sequences keep separate turns", () => {
  assert.equal(groupTranscriptTurns([segment(0, "A", 0, 1), segment(1, "A", 3.001, 4)]).length, 2);
  assert.equal(groupTranscriptTurns([segment(0, "A", 0, 1), segment(2, "A", 1.1, 2)]).length, 2);
  assert.equal(groupTranscriptTurns([segment(0, "A", 0, 1), segment(1, "A", 3, 4)]).length, 1);
});

test("overlapping or flagged speech stays separate", () => {
  assert.equal(groupTranscriptTurns([segment(0, "A", 0, 2), segment(1, "A", 1, 3)]).length, 2);
  assert.equal(groupTranscriptTurns([segment(0, "A", 0, 1, { is_overlap: true }), segment(1, "A", 1, 2)]).length, 2);
  assert.equal(groupTranscriptTurns([segment(0, "A", 0, 1), segment(1, "A", 1, 2, { is_overlap: true })]).length, 2);
});

test("a transcription window boundary alone does not split a reading turn", () => {
  assert.equal(groupTranscriptTurns([segment(0, "A", 0, 28), segment(1, "A", 28, 56)]).length, 1);
});

test("corrections are searchable across fragments and remain tied to their source ID", () => {
  const first = segment(0, "A", 0, 1, { original_text: "الأصل", edited_text: "النص المصحح", edited_by_name: "المراجع" });
  const second = segment(1, "A", 1.1, 2, { original_text: "يستمر هنا" });
  const [turn] = groupTranscriptTurns([first, second]);
  assert.equal(turn.text, "النص المصحح يستمر هنا");
  assert.ok(turn.text.includes("المصحح يستمر"));
  assert.equal(turn.segments[0].id, first.id);
  assert.equal(turn.segments[0].original_text, "الأصل");
  assert.equal(turn.segments[0].edited_by_name, "المراجع");
  assert.equal(groupTranscriptTurns([segment(0, "A", 0, 1, { edited_text: "" })])[0].text, "");
});

test("invalid times are not merged, and empty input remains empty", () => {
  assert.equal(groupTranscriptTurns([segment(0, "A", 0, 1), segment(1, "A", NaN, 3)]).length, 2);
  assert.deepEqual(groupTranscriptTurns([]), []);
});

test("source timestamps retain fractions and carry rounded milliseconds across minutes and hours", () => {
  assert.equal(formatTimestamp(1.84), "00:00:01.840");
  assert.equal(formatTimestamp(59.9996), "00:01:00.000");
  assert.equal(formatTimestamp(3599.9996), "01:00:00.000");
  assert.equal(formatTimestamp(0), "00:00:00.000");
  assert.equal(formatTimestamp(NaN), "—");
});
