import type { Speaker, Segment } from "@/api/types";

/** Only an established canonical identity groups observations. Names never do. */
export function groupSpeakerObservations(speakers: Speaker[]) {
  const groups = new Map<string, { key: string; name: string; identified: boolean; observations: Speaker[]; segmentCount: number; totalSeconds: number }>();
  for (const speaker of speakers) {
    const key = speaker.identity_id ? `person:${speaker.identity_id}` : `observation:${speaker.id}`;
    const group = groups.get(key) ?? { key, name: speaker.identity_name || speaker.display_name || "متحدث غير محدد",
      identified: Boolean(speaker.identity_id), observations: [], segmentCount: 0, totalSeconds: 0 };
    group.observations.push(speaker);
    group.segmentCount += speaker.segment_count;
    group.totalSeconds += speaker.total_seconds;
    groups.set(key, group);
  }
  return [...groups.values()];
}

export function transcriptSpeakerOptions(speakers: Speaker[], segments: Segment[]) {
  const present = new Set(segments.map(s => s.speaker_label));
  const groups = new Map<string, { key: string; name: string; labels: string[] }>();
  for (const label of present) {
    const speaker = speakers.find(s => s.speaker_label === label);
    const key = speaker?.identity_id ? `person:${speaker.identity_id}` : `speaker:${label}`;
    const group = groups.get(key) ?? { key, name: speaker?.identity_name || speaker?.display_name || label, labels: [] };
    group.labels.push(label);
    groups.set(key, group);
  }
  const options = [...groups.values()];
  // Same name never means same person. Disambiguate distinct identities visibly.
  return options.map(option => ({ ...option, name: options.some(other => other.key !== option.key && other.name === option.name)
    ? `${option.name} (${option.labels.join(', ')})` : option.name }));
}
