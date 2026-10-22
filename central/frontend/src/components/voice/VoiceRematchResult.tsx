import type { VoiceRematchOutcome } from "@/api/types";
import { Alert } from "@/components/ui";
import { T } from "@/lib/i18n";

/** Keep the reasons visible after the short completion toast disappears. */
export function VoiceRematchResult({ result }: { result: VoiceRematchOutcome }) {
  const reasons: [number | undefined, string][] = [
    [result.no_sample, T.voiceRematchNoSample],
    [result.no_compatible_enrollment, T.voiceRematchNoCompatible],
    [result.below_threshold, T.voiceRematchBelowThreshold],
    [result.ambiguous, T.voiceRematchAmbiguous],
    [result.skipped_decided, T.voiceRematchSkippedDecided],
  ];
  return <div className="mb-16" role="status" data-testid="voice-rematch-result">
    <Alert kind={result.suggested > 0 ? "success" : "info"}>
      <strong>{T.voiceRematchResults}</strong>
      <p>{T.voiceRematchScanned.replace("{n}", String(result.scanned))} · {T.voiceRematchSuggested.replace("{n}", String(result.suggested))}</p>
      {reasons.some(([count]) => (count ?? 0) > 0) && <ul style={{ margin: "4px 0 0", paddingInlineStart: 18 }}>
        {reasons.filter(([count]) => (count ?? 0) > 0).map(([count, message]) => <li key={message}>{message.replace("{n}", String(count))}</li>)}
      </ul>}
    </Alert>
  </div>;
}
