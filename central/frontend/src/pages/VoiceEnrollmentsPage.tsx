import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { ApiError, http, qs } from "@/api/client";
import type { VoiceEnrollment } from "@/api/types";
import { useAuth } from "@/lib/auth";
import { formatDateTime, formatDuration } from "@/lib/format";
import { T, errorMessage } from "@/lib/i18n";
import { Alert, Badge, Loading, useToast } from "@/components/ui";
import { IconRefresh, IconSearch } from "@/components/Icons";

export function VoiceEnrollmentsPage() {
  const toast = useToast();
  const { can } = useAuth();
  const [rows, setRows] = useState<VoiceEnrollment[] | null>(null);
  const [q, setQ] = useState("");
  const [includeInactive, setIncludeInactive] = useState(true);
  const manage = can("voice.enroll");
  const [rematching, setRematching] = useState(false);

  const load = useCallback(() => {
    void http
      .get<VoiceEnrollment[]>(`/voice-enrollments${qs({ q, include_inactive: includeInactive })}`)
      .then(setRows)
      .catch(() => setRows([]));
  }, [q, includeInactive]);

  useEffect(() => {
    const h = setTimeout(load, 200);
    return () => clearTimeout(h);
  }, [load]);

  /* Matching runs when a result is submitted, so sessions processed before a person was
     enrolled stay unidentified. This re-checks only speakers still at "غير محدد" - it
     never disturbs a session an investigator has already decided. */
  const rematchAll = async () => {
    setRematching(true);
    try {
      const res = await http.post<{ sessions: number; scanned: number; suggested: number }>(
        "/voice-enrollments/rematch",
        {},
      );
      toast.success(
        res.suggested > 0 ? T.voiceRematchDone.replace("{n}", String(res.suggested)) : T.voiceRematchNone,
      );
    } catch (err) {
      toast.error(err instanceof ApiError ? errorMessage(err.code) : T.err_generic);
    } finally {
      setRematching(false);
    }
  };

  const setActive = async (row: VoiceEnrollment, is_active: boolean) => {
    try {
      await http.patch(`/voice-enrollments/${row.id}`, { is_active });
      toast.success(T.voiceUpdated);
      load();
    } catch (err) {
      toast.error(err instanceof ApiError ? errorMessage(err.code) : T.err_generic);
    }
  };

  const remove = async (row: VoiceEnrollment) => {
    if (!window.confirm(`${T.voiceDeleteConfirm}\n\n${row.person_name} (${row.person_reference})`)) return;
    try {
      await http.del(`/voice-enrollments/${row.id}`);
      toast.success(T.voiceDeleted);
      load();
    } catch (err) {
      toast.error(err instanceof ApiError ? errorMessage(err.code) : T.err_generic);
    }
  };

  return (
    <>
      <div className="page-header">
        <div>
          <h1>{T.voiceEnrollments}</h1>
          <p>{T.voiceRegistryIntro}</p>
        </div>
        {can("voice.identify") && (
          <button
            className="btn"
            type="button"
            onClick={rematchAll}
            disabled={rematching}
            data-testid="voice-rematch-all"
          >
            <IconRefresh /> {rematching ? T.voiceRematchRunning : T.voiceRematchAll}
          </button>
        )}
        <button className="btn" type="button" onClick={load}>
          <IconRefresh /> {T.refresh}
        </button>
      </div>

      <div className="card">
        <div className="toolbar">
          <div className="flex" style={{ position: "relative" }}>
            <input className="input search" placeholder={`${T.search}…`} value={q} onChange={(e) => setQ(e.target.value)} />
            <IconSearch style={{ position: "absolute", insetInlineEnd: 10, top: 9, color: "var(--muted)" }} width={16} height={16} />
          </div>
          <label className="checkbox">
            <input type="checkbox" checked={includeInactive} onChange={(e) => setIncludeInactive(e.target.checked)} />
            {T.voiceInactive}
          </label>
        </div>
        {!rows ? (
          <Loading />
        ) : rows.length === 0 ? (
          <div className="card-body muted center">{T.voiceNoEnrollments}</div>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>{T.voicePersonName}</th>
                  <th>{T.voicePersonReference}</th>
                  <th>{T.voiceModel}</th>
                  <th>{T.voiceSampleLength}</th>
                  <th>{T.voiceSourceSession}</th>
                  <th>{T.voiceConsent}</th>
                  <th>{T.status}</th>
                  <th>{T.voiceEnrolledBy}</th>
                  <th>{T.createdAt}</th>
                  {manage && <th>{T.actions}</th>}
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id} data-testid="enrollment-row">
                    <td>{r.person_name}</td>
                    <td className="ltr">{r.person_reference}</td>
                    <td className="ltr small">
                      {r.model}
                      <br />
                      <span className="muted">{r.model_revision ?? ""}</span>
                    </td>
                    <td>{formatDuration(r.sample_seconds)}</td>
                    <td className="small">
                      {r.source_session_id ? (
                        <Link to={`/investigations/${r.source_session_id}?tab=speakers`}>
                          <span className="ltr">{r.source_speaker_label ?? T.view}</span>
                        </Link>
                      ) : (
                        T.none
                      )}
                    </td>
                    <td>
                      <Badge kind={r.consent_recorded ? "green" : "red"}>{r.consent_recorded ? T.yes : T.no}</Badge>
                    </td>
                    <td>
                      <Badge kind={r.is_active ? "green" : "gray"}>{r.is_active ? T.voiceActive : T.voiceInactive}</Badge>
                    </td>
                    <td>{r.enrolled_by_name ?? T.none}</td>
                    <td className="num">{formatDateTime(r.created_at)}</td>
                    {manage && (
                      <td className="actions-cell">
                        <div className="flex">
                          <button className="btn btn-sm" type="button" onClick={() => void setActive(r, !r.is_active)}>
                            {r.is_active ? T.voiceDeactivate : T.voiceActivate}
                          </button>
                          <button className="btn btn-sm btn-danger" type="button" onClick={() => void remove(r)}>
                            {T.voiceDelete}
                          </button>
                        </div>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="mt-16">
        <Alert kind="info">{T.voiceSuggestionHint}</Alert>
      </div>
    </>
  );
}
