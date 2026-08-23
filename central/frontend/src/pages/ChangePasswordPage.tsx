import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";

import { ApiError, http } from "@/api/client";
import { useAuth } from "@/lib/auth";
import { T, errorMessage } from "@/lib/i18n";
import { Alert, Field, useToast } from "@/components/ui";

export function ChangePasswordPage() {
  const { user, refresh } = useAuth();
  const toast = useToast();
  const navigate = useNavigate();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (next !== confirm) {
      setError(T.passwordsMismatch);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await http.post("/auth/change-password", { current_password: current, new_password: next });
      await refresh();
      toast.success(T.passwordChanged);
      navigate("/");
    } catch (err) {
      setError(err instanceof ApiError ? errorMessage(err.code) : T.err_generic);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div className="page-header">
        <h1>{T.changePassword}</h1>
      </div>
      <div className="card" style={{ maxWidth: 560 }}>
        <form className="card-body" onSubmit={submit}>
          {user?.must_change_password && (
            <div className="mb-16">
              <Alert kind="warning">{T.mustChangePasswordNotice}</Alert>
            </div>
          )}
          {error && (
            <div className="mb-16">
              <Alert kind="danger">{error}</Alert>
            </div>
          )}
          <div className="form-grid" style={{ gridTemplateColumns: "1fr" }}>
            <Field label={T.currentPassword} required>
              <input className="input" type="password" value={current} onChange={(e) => setCurrent(e.target.value)} autoComplete="current-password" required dir="ltr" />
            </Field>
            <Field label={T.newPassword} required hint={T.passwordPolicy}>
              <input className="input" type="password" value={next} onChange={(e) => setNext(e.target.value)} autoComplete="new-password" minLength={10} required dir="ltr" />
            </Field>
            <Field label={T.confirmPassword} required>
              <input className="input" type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="new-password" required dir="ltr" />
            </Field>
          </div>
          <div className="form-actions">
            <button className="btn btn-primary" type="submit" disabled={busy}>
              {T.save}
            </button>
          </div>
        </form>
      </div>
    </>
  );
}
