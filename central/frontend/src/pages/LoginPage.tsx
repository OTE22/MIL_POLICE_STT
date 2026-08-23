import { useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";

import { ApiError } from "@/api/client";
import { useAuth } from "@/lib/auth";
import { T, errorMessage } from "@/lib/i18n";
import { Alert } from "@/components/ui";
import { IconCpu, IconMic, IconShield, IconWave } from "@/components/Icons";

export function LoginPage() {
  const { user, login, loading } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (!loading && user) return <Navigate to="/" replace />;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const me = await login(username.trim(), password);
      const from = (location.state as { from?: string } | null)?.from;
      navigate(me.must_change_password ? "/change-password" : from || "/", { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? errorMessage(err.code) : T.err_generic);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login-page">
      <section className="login-brand">
        <h1>{T.appName}</h1>
        <p>{T.orgLine}. تسجيل الجلسات، فصل المتحدثين، وتفريغ النصوص العربية محلياً على جهاز المحقق مع حفظ مركزي وسجل تدقيق كامل.</p>
        <div className="features">
          <div>
            <IconMic /> تسجيل الجلسات من المتصفح أو رفع الملفات الصوتية
          </div>
          <div>
            <IconWave /> فصل المتحدثين وتحويل الصوت إلى نص عربي على الجهاز المحلي
          </div>
          <div>
            <IconCpu /> لا يتم إرسال الصوت إلى أي خدمة خارجية
          </div>
          <div>
            <IconShield /> صلاحيات دقيقة وسجل تدقيق لكل إجراء
          </div>
        </div>
      </section>
      <section className="login-form-wrap">
        <form className="login-form card" onSubmit={submit} style={{ padding: 32 }} noValidate>
          <h2>{T.login}</h2>
          <p className="sub">{T.loginHint}</p>
          {error && (
            <div className="mb-16">
              <Alert kind="danger">{error}</Alert>
            </div>
          )}
          <div className="field mb-16">
            <label htmlFor="username">{T.username}</label>
            <input
              id="username"
              className="input"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              autoFocus
              required
              dir="ltr"
              style={{ textAlign: "right" }}
            />
          </div>
          <div className="field mb-16">
            <label htmlFor="password">{T.password}</label>
            <input
              id="password"
              className="input"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              required
              dir="ltr"
              style={{ textAlign: "right" }}
            />
          </div>
          <button className="btn btn-primary btn-lg btn-block" type="submit" disabled={busy || !username || !password}>
            {busy ? <span className="spinner" /> : null} {T.login}
          </button>
        </form>
      </section>
    </div>
  );
}
