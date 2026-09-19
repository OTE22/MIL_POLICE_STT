/* The one consent-gated enrolment form.
 *
 * Both callers - the speaker card inside a session, and بانتظار التسجيل on the voice page -
 * use this dialog and the same existing endpoint. Duplicating the form would mean two
 * consent gates and two chances for one of them to drift.
 */

import { useEffect, useState } from "react";

import { ApiError, http } from "@/api/client";
import type { VoiceEnrollment } from "@/api/types";
import { T, errorMessage } from "@/lib/i18n";
import { Alert, Field, Modal, useToast } from "@/components/ui";

export const SPEAKER_ID_MODEL = "nvidia/speakerverification_speakernet";

export interface EnrollTarget {
  sessionId: string;
  speakerId: string;
  personName: string;
  /** Internal person UUID; never displayed or typed. */
  identityId: string;
  model?: string | null;
  sampleSeconds?: number | null;
}

export function EnrollDialog({
  target,
  onClose,
  onEnrolled,
}: {
  target: EnrollTarget;
  onClose: () => void;
  onEnrolled: (enrollment: VoiceEnrollment) => void;
}) {
  const toast = useToast();
  const [personName, setPersonName] = useState(target.personName);
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setPersonName(target.personName);
    setConsent(false);
    setError(null);
  }, [target]);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const created = await http.post<VoiceEnrollment>(
        `/investigations/${target.sessionId}/speakers/${target.speakerId}/enroll`,
        {
          // The name is shown for confirmation only. They are NOT sent:
          // the server reads the person from the speaker's identity, and letting a client
          // name the subject of a biometric record is exactly the wrong authority.
          model: target.model || SPEAKER_ID_MODEL,
          provider: "nemo_speakernet",
          sample_seconds: target.sampleSeconds ?? null,
          consent_recorded: consent,
        },
      );
      toast.success(T.voiceEnrolled);
      onEnrolled(created);
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? errorMessage(err.code) : T.err_generic);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      title={T.voiceEnrollTitle}
      onClose={onClose}
      footer={
        <>
          <button
            className="btn btn-primary"
            type="button"
            // Consent is not optional: the API refuses without it, and the button must not
            // suggest otherwise.
            disabled={busy || !consent || !personName.trim() || !target.identityId}
            onClick={() => void submit()}
            data-testid="voice-enroll-submit"
          >
            {T.voiceEnroll}
          </button>
          <button className="btn" type="button" onClick={onClose}>
            {T.cancel}
          </button>
        </>
      }
    >
      <p className="muted small mb-16">{T.voiceEnrollIntro}</p>
      {error && (
        <div className="mb-16">
          <Alert kind="danger">{error}</Alert>
        </div>
      )}
      {/* Both read-only. The print is filed against the speaker's canonical identity, which
          the server resolves itself - it ignores whatever is sent here. Leaving these editable
          implied an operator could file a print under a different person by typing one, which
          was never true and is exactly the confusion this whole area had to unpick. */}
      <Field label={T.voicePersonName}>
        <input className="input" value={personName} readOnly data-testid="voice-enroll-person" />
      </Field>
      <label className="checkbox">
        <input
          type="checkbox"
          checked={consent}
          onChange={(e) => setConsent(e.target.checked)}
          data-testid="voice-consent"
        />
        {T.voiceConsent}
      </label>
      {!consent && <div className="error-text">{T.voiceConsentRequired}</div>}
    </Modal>
  );
}
