import { useRef, useState } from "react";
import { confirmResume, requestResume, selectResume } from "./api";
import { formatMexicoDateTime } from "./mexicoTime";

export default function ResumeByEmail({ phone, studies, clinics, onSelected, onClose }) {
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [challenge, setChallenge] = useState(null);
  const [items, setItems] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const keys = useRef(new Map());

  async function run(action) {
    setBusy(true);
    setError("");
    try {
      await action();
    } catch (reason) {
      setError(reason.attempts_remaining == null ? reason.message
        : `${reason.message} Intentos restantes: ${reason.attempts_remaining}.`);
    } finally {
      setBusy(false);
    }
  }

  function submit(event) {
    event.preventDefault();
    run(async () => {
      if (!challenge) setChallenge(await requestResume(email, phone));
      else setItems((await confirmResume(challenge.challenge_id, code)).items);
    });
  }

  return (
    <section className="my-4 rounded-xl border border-slate-200 bg-white p-4">
      <h2 className="font-semibold">Retomar con mi correo</h2>
      {error && <p role="alert" className="my-2 text-red-700">{error}</p>}
      {items ? (
        <ul className="my-3 space-y-2">
          {items.length === 0 && <li>No hay trámites ni borradores disponibles.</li>}
          {items.map((item) => (
            <li key={item.id}>
              <button type="button" className="option-button w-full" disabled={busy} onClick={() => run(async () => {
                if (!keys.current.has(item.id)) keys.current.set(item.id, crypto.randomUUID());
                const selected = await selectResume(challenge.challenge_id, item, keys.current.get(item.id));
                await onSelected(selected, challenge.challenge_id);
              })}>
                {studies.find((study) => study.id === item.study_id)?.name ?? "Estudio por elegir"}
                <span className="block text-sm font-normal">
                  {clinics.find((clinic) => clinic.id === item.clinic_id)?.name ?? "Clínica por elegir"}
                  {" · "}{item.status.replaceAll("_", " ")}{" · "}{item.channel}
                  {" · Para: "}{item.patient_name ?? "Paciente por indicar"}
                  {" · "}{formatMexicoDateTime(item.updated_at)}
                </span>
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <form className="my-3 space-y-3" onSubmit={submit}>
          {challenge ? <>
            <p>{challenge.message}</p>
            <label className="field">Código de seis dígitos
              <input required type="password" inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" maxLength={6} value={code} onChange={(event) => setCode(event.target.value)} />
            </label>
            <a className="block text-cyan-800 underline" target="_blank" rel="noreferrer" href={`/mailbox?email=${encodeURIComponent(email)}`}>Abrir buzón simulado</a>
          </> : (
            <label className="field">Correo electrónico
              <input required type="email" value={email} onChange={(event) => setEmail(event.target.value)} />
            </label>
          )}
          <button className="button-primary" disabled={busy}>{challenge ? "Verificar código" : "Solicitar código"}</button>
        </form>
      )}
      <button type="button" className="text-sm underline" disabled={busy} onClick={onClose}>Volver</button>
    </section>
  );
}
