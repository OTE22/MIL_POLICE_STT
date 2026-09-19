/* إعدادات النظام — runtime configuration, rendered entirely from the backend's whitelist.
 *
 * The page never defines a field itself: it renders whatever GET /admin/config sends.
 * That keeps the decision of what is safe to expose in ONE place (the backend registry),
 * where secrets and boot-structural settings simply are not listed. Changes apply to the
 * running server immediately and are deliberately EPHEMERAL - a restart returns to the
 * environment file, so a bad interactive change is one restart away from undone.
 */

import { useCallback, useEffect, useMemo, useState } from "react";

import { ApiError, http } from "@/api/client";
import type { ConfigField, ConfigOut } from "@/api/types";
import { T, errorMessage } from "@/lib/i18n";
import { Alert, Field, Loading, useToast } from "@/components/ui";

export function SystemConfigPage() {
  const toast = useToast();
  const [fields, setFields] = useState<ConfigField[] | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const res = await http.get<ConfigOut>("/admin/config");
    setFields(res.fields);
    setDraft(Object.fromEntries(res.fields.map((f) => [f.key, String(f.value)])));
  }, []);

  useEffect(() => {
    void load().catch(() => setFields([]));
  }, [load]);

  const groups = useMemo(() => {
    const out = new Map<string, ConfigField[]>();
    for (const f of fields ?? []) {
      out.set(f.group, [...(out.get(f.group) ?? []), f]);
    }
    return out;
  }, [fields]);

  const dirty = useMemo(
    () => (fields ?? []).filter((f) => draft[f.key] !== String(f.value)),
    [fields, draft],
  );

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      // Send only what changed - the log then records exactly the deltas.
      const values: Record<string, string> = {};
      for (const f of dirty) values[f.key] = draft[f.key];
      const res = await http.put<ConfigOut>("/admin/config", { values });
      setFields(res.fields);
      setDraft(Object.fromEntries(res.fields.map((f) => [f.key, String(f.value)])));
      toast.success(T.configSaved);
    } catch (err) {
      setError(err instanceof ApiError ? errorMessage(err.code) : T.err_generic);
    } finally {
      setBusy(false);
    }
  };

  if (fields === null) return <Loading />;

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h2>{T.systemConfig}</h2>
          <p className="muted">{T.systemConfigHint}</p>
        </div>
        <button
          className="btn btn-primary"
          type="button"
          disabled={busy || dirty.length === 0}
          onClick={() => void save()}
          data-testid="config-save"
        >
          {busy ? T.saving : T.save}
          {dirty.length > 0 ? ` (${dirty.length})` : ""}
        </button>
      </div>

      <Alert kind="info">{T.configEphemeral}</Alert>
      {error && <div className="mt-16"><Alert kind="danger">{error}</Alert></div>}

      {[...groups.entries()].map(([group, groupFields]) => (
        <div className="card mt-16" key={group}>
          <div className="card-header"><h3>{group}</h3></div>
          <div className="card-body">
            <div className="form-grid">
              {groupFields.map((f) => (
                <Field key={f.key} label={f.label} hint={f.description}>
                  {f.type === "bool" ? (
                    <label className="checkbox">
                      {/* The draft holds every value as a string (see load()); the backend
                          coerces "true"/"false" back to a boolean. */}
                      <input
                        type="checkbox"
                        checked={draft[f.key] === "true"}
                        onChange={(e) => setDraft((d) => ({ ...d, [f.key]: String(e.target.checked) }))}
                        data-testid={`config-${f.key}`}
                      />
                      {draft[f.key] === "true" ? T.enabled : T.disabled}
                    </label>
                  ) : f.type === "select" ? (
                    <select
                      className="select"
                      value={draft[f.key] ?? ""}
                      onChange={(e) => setDraft((d) => ({ ...d, [f.key]: e.target.value }))}
                      data-testid={`config-${f.key}`}
                    >
                      {(f.options ?? []).map((o) => (
                        <option key={o} value={o}>{o}</option>
                      ))}
                    </select>
                  ) : (
                    <input
                      className={`input ${f.type === "text" ? "ltr" : "num"}`}
                      type={f.type === "text" ? "text" : "number"}
                      step={f.type === "float" ? "0.01" : "1"}
                      min={f.min ?? undefined}
                      max={f.max ?? undefined}
                      value={draft[f.key] ?? ""}
                      onChange={(e) => setDraft((d) => ({ ...d, [f.key]: e.target.value }))}
                      data-testid={`config-${f.key}`}
                    />
                  )}
                </Field>
              ))}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
