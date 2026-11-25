import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { staffLogin } from "../api";

export default function Login() {
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function submit(event) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      const session = await staffLogin(username, password);
      setPassword("");
      if (session.role === "asesor") navigate("/callcenter", { replace: true });
      else navigate("/admin", { replace: true });
    } catch (reason) {
      setError(reason.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="mx-auto max-w-md p-6">
      <form onSubmit={submit} className="space-y-4 rounded-xl bg-white p-6 shadow-sm">
        <h1 className="text-2xl font-bold">Acceso de personal</h1>
        <label className="field">Usuario
          <input autoComplete="username" required value={username} onChange={(event) => setUsername(event.target.value)} />
        </label>
        <label className="field">Contraseña
          <input type="password" autoComplete="current-password" required value={password} onChange={(event) => setPassword(event.target.value)} />
        </label>
        {error && <p role="alert" className="text-red-700">{error}</p>}
        <button className="button-primary" disabled={loading}>{loading ? "Ingresando…" : "Iniciar sesión"}</button>
      </form>
    </main>
  );
}
