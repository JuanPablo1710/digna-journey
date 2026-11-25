import { useEffect, useRef, useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import {
  canSimulateNewDevice, getAdminAudit, getAdminCases, getAdminDashboard, getStaffSession,
  openStaffStream, resetAdminDemo, seedAdminDemo, staffLogout,
} from "../api";
import { formatMexicoDateTime } from "../mexicoTime";

const states = {
  cotizando: "Cotizando", datos_completos: "Datos completos", clinica_elegida: "Clínica elegida",
  horario_propuesto: "Horario propuesto", cita_confirmada: "Cita confirmada", cancelado: "Cancelado",
};
const channels = {
  web: ["Web", "bg-blue-100 text-blue-950"],
  whatsapp: ["WhatsApp", "bg-emerald-100 text-emerald-950"],
  callcenter: ["Call Center", "bg-violet-100 text-violet-950"],
  app: ["App", "bg-orange-100 text-orange-950"],
  admin: ["Admin", "bg-slate-200 text-slate-950"],
};
const auditTypes = {
  contexto_consultado: "Contexto consultado", acceso_denegado: "Acceso denegado",
  verificacion_solicitada: "Verificación solicitada", verificacion_exitosa: "Verificación exitosa",
  verificacion_fallida: "Verificación fallida",
};

function Channel({ value }) {
  const [label, color] = channels[value] ?? ["Sin canal", "bg-gray-100 text-gray-700"];
  return <span className={`whitespace-nowrap rounded-md px-2 py-1 text-sm font-semibold ${color}`}>{label}</span>;
}

function MaskedContact({ person }) {
  if (!person) return <span>Sin contacto</span>;
  return <div><strong className="block">{person.name}</strong><span>{person.phone}</span><span className="block">{person.email}</span></div>;
}

function EventList({ events, live = false }) {
  if (!events.length) return <p className="mt-4 text-slate-600">Todavía no hay eventos.</p>;
  return <ol className="mt-4 divide-y divide-slate-200">{events.map((item) => (
    <li key={item.cursor} className={`flex flex-wrap items-center gap-x-3 gap-y-2 rounded px-3 py-3 ${live && item.live ? "admin-event-arrival" : ""}`}>
      <span className="font-medium">{item.summary}</span>
      <Channel value={item.channel} />
      {item.case_id && <span>{item.case_id}</span>}
      {item.actor && <span className="text-sm text-slate-700">{item.actor.role ?? "Actor sin registrar"}{item.actor.id && ` · ${item.actor.id}`}</span>}
      {item.person && <span className="text-sm text-slate-700">{item.person.name} · {item.person.phone} · {item.person.email}</span>}
      <time dateTime={item.timestamp} className="text-sm text-slate-600 sm:ml-auto">{formatMexicoDateTime(item.timestamp)}</time>
    </li>
  ))}</ol>;
}

export default function Admin() {
  const navigate = useNavigate();
  const authorized = getStaffSession()?.role === "admin";
  const [dashboard, setDashboard] = useState(null);
  const [streamCursor, setStreamCursor] = useState(null);
  const [feed, setFeed] = useState([]);
  const [cases, setCases] = useState([]);
  const [audit, setAudit] = useState([]);
  const [auditType, setAuditType] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [channelFilter, setChannelFilter] = useState("");
  const [connection, setConnection] = useState("reconnecting");
  const [revision, setRevision] = useState(0);
  const [demo, setDemo] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [feedback, setFeedback] = useState("");
  const activeStream = useRef(null);

  function logout() {
    activeStream.current?.();
    staffLogout();
    navigate("/login", { replace: true });
  }

  function handleError(reason) {
    if (reason.status === 401 || reason.error === "invalid_token" || reason.error === "authentication_required") logout();
    else setError(reason.message);
  }

  useEffect(() => {
    if (!authorized) return;
    let active = true;
    const controller = new AbortController();
    canSimulateNewDevice(controller.signal).then((visible) => { if (active) setDemo(visible); }).catch(() => {});
    return () => { active = false; controller.abort(); };
  }, [authorized]);

  useEffect(() => {
    if (!authorized) return;
    let active = true;
    Promise.all([getAdminDashboard(), getAdminAudit()]).then(([metrics, log]) => {
      if (!active) return;
      setDashboard(metrics);
      setAudit(log.entries);
      if (streamCursor == null) {
        setFeed(metrics.recent_events);
        setStreamCursor(metrics.cursor);
      }
    }).catch((reason) => { if (active) handleError(reason); });
    return () => { active = false; };
  }, [authorized, revision]);

  useEffect(() => {
    if (!authorized) return;
    let active = true;
    getAdminCases(statusFilter, channelFilter).then((data) => {
      if (active) setCases(data.cases);
    }).catch((reason) => { if (active) handleError(reason); });
    return () => { active = false; };
  }, [authorized, statusFilter, channelFilter, revision]);

  useEffect(() => {
    if (!authorized || streamCursor == null) return;
    let refresh;
    const stop = openStaffStream({
      cursor: streamCursor,
      onStatus: setConnection,
      onError: handleError,
      onEvent(event, cursor) {
        setFeed((previous) => [{ ...event, cursor, live: true }, ...previous].slice(0, 20));
        if (!refresh) refresh = window.setTimeout(() => {
          refresh = undefined;
          setRevision((value) => value + 1);
        }, 300);
      },
    });
    activeStream.current = stop;
    return () => {
      stop();
      window.clearTimeout(refresh);
      activeStream.current = null;
    };
  }, [authorized, streamCursor]);

  if (!authorized) return <Navigate to="/login" replace />;

  async function run(task, message) {
    setBusy(true);
    setError("");
    setFeedback("");
    try {
      await task();
      if (message) setFeedback(message);
    } catch (reason) {
      handleError(reason);
    } finally {
      setBusy(false);
    }
  }

  function reset() {
    if (!window.confirm("¿Reiniciar la demo? Se reemplazarán los datos y tendrás que volver a iniciar sesión.")) return;
    run(async () => {
      await resetAdminDemo();
      logout();
    });
  }

  const average = dashboard?.average_confirmation_seconds;
  const funnelMax = Math.max(1, ...(dashboard?.funnel ?? []).map((step) => step.count));
  const kpis = [
    ["Trámites", dashboard?.total_cases],
    ["Abandonados", dashboard?.abandoned],
    ["Recuperados entre canales", dashboard?.recovered_across_channels],
    ["Promedio hasta confirmar", average == null ? null : `${Math.round(average / 60).toLocaleString("es-MX")} min`],
  ];

  return (
    <main className="mx-auto max-w-7xl space-y-6 px-5 py-8 text-base lg:text-lg">
      <header className="flex flex-wrap items-center justify-between gap-4 rounded-2xl bg-slate-900 p-5 text-white sm:p-7">
        <h1 className="text-3xl font-bold">Tablero de administración</h1>
        <div className="flex flex-wrap items-center gap-4">
          <span role="status" className="rounded bg-slate-700 px-3 py-2 text-base font-semibold">
            {connection === "connected" ? "Conectado" : connection === "disconnected" ? "Sin conexión" : "Reconectando..."}
          </span>
          <button className="underline" type="button" onClick={logout}>Cerrar sesión</button>
        </div>
      </header>
      {error && <p role="alert" className="rounded-lg bg-red-50 p-4 text-red-800">{error}</p>}
      {feedback && <p role="status" className="rounded-lg bg-emerald-50 p-4 text-emerald-900">{feedback}</p>}
      {!dashboard && !error && <p role="status">Cargando tablero…</p>}
      {demo && <section aria-label="Operaciones de demo" className="flex flex-wrap gap-3">
        <button className="option-button bg-white" disabled={busy} onClick={() => run(async () => {
          await seedAdminDemo();
          setRevision((value) => value + 1);
        }, "Datos de demo comprobados.")}>Cargar datos faltantes</button>
        <button className="option-button bg-white text-red-800" disabled={busy} onClick={reset}>Reiniciar demo</button>
      </section>}
      <section aria-label="Indicadores" className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {kpis.map(([label, value]) => <article key={label} className="rounded-xl border border-slate-200 bg-white p-4">
          <p className="font-semibold text-slate-700">{label}</p>
          <p className="mt-2 text-3xl font-bold tabular-nums">{value ?? "—"}</p>
        </article>)}
      </section>
      {dashboard && <section className="rounded-xl border border-slate-200 bg-white p-5">
        <h2 className="text-xl font-bold">Embudo de trámites</h2>
        <ol className="mt-4 space-y-3">
          {dashboard.funnel.map((step) => <li key={step.status} className="grid grid-cols-[minmax(8rem,13rem)_1fr_2rem] items-center gap-3">
            <span>{states[step.status]}</span>
            <div className="h-4 rounded-full bg-slate-100" aria-hidden="true"><div className="h-4 rounded-full bg-cyan-700" style={{ width: `${100 * step.count / funnelMax}%` }} /></div>
            <strong className="text-right tabular-nums">{step.count}</strong>
          </li>)}
        </ol>
        <p className="mt-3 text-sm text-slate-700">Cancelados: {dashboard.totals_by_status.cancelado}. El embudo cuenta el estado actual de cada trámite.</p>
      </section>}
      <section className="rounded-xl border border-slate-200 bg-white p-5">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <h2 className="text-xl font-bold">Trámites</h2>
          <div className="flex flex-wrap gap-3">
            <label className="field">Estado<select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
              <option value="">Todos</option>
              {Object.entries(states).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select></label>
            <label className="field">Canal<select value={channelFilter} onChange={(event) => setChannelFilter(event.target.value)}>
              <option value="">Todos</option>
              {Object.entries(channels).filter(([value]) => value !== "admin").map(([value, [label]]) => <option key={value} value={value}>{label}</option>)}
            </select></label>
          </div>
        </div>
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[620px] text-left">
            <thead className="bg-slate-100"><tr>
              {["Folio", "Solicitante", "Paciente", "Estado", "Recorrido"].map((title) => <th scope="col" className="p-3" key={title}>{title}</th>)}
            </tr></thead>
            <tbody className="divide-y divide-slate-200">{cases.map((item) => <tr key={item.id}>
              <th scope="row" className="p-3 align-top">{item.id}</th>
              <td className="p-3 align-top text-sm"><MaskedContact person={item.requester} /></td>
              <td className="p-3 align-top text-sm"><MaskedContact person={item.patient} /></td>
              <td className="p-3 align-top">{states[item.status] ?? item.status}{item.abandoned && <span className="block text-amber-900">Abandonado</span>}</td>
              <td className="p-3 align-top"><ol className="flex flex-wrap items-center gap-2">{item.channels.map((channel, index) => <li key={`${channel}-${index}`} className="flex items-center gap-2">{index > 0 && <span aria-hidden="true">→</span>}<Channel value={channel} /></li>)}</ol></td>
            </tr>)}</tbody>
          </table>
        </div>
        {dashboard && cases.length === 0 && <p className="mt-4 text-slate-600">No hay trámites para estos filtros.</p>}
      </section>
      <section className="rounded-xl border border-slate-200 bg-white p-5">
        <h2 className="text-xl font-bold">Eventos en vivo</h2>
        <EventList events={feed} live />
      </section>
      <section className="rounded-xl border border-slate-200 bg-white p-5">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <h2 className="text-xl font-bold">Bitácora de auditoría</h2>
          <label className="field">Tipo de evento
            <select value={auditType} onChange={(event) => setAuditType(event.target.value)}>
              <option value="">Todos</option>
              {Object.entries(auditTypes).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </label>
        </div>
        <EventList events={auditType ? audit.filter((event) => event.type === auditType) : audit} />
      </section>
    </main>
  );
}
