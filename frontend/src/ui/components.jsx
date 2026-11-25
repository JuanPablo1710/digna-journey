const statuses = {
  cotizando: "Cotizando", datos_completos: "Datos completos", clinica_elegida: "Clínica elegida",
  horario_propuesto: "Horario propuesto", cita_confirmada: "Cita confirmada", cancelado: "Cancelado",
};
const channels = {
  app: ["App", "▣"], web: ["Web", "◉"], whatsapp: ["WhatsApp", "✉"], callcenter: ["Call Center", "☎"],
};

export function Button({ secondary, children, ...props }) {
  return <button type="button" {...props} className={`app-button${secondary ? " app-button-secondary" : ""}`}>{children}</button>;
}

export function Card({ children, ...props }) {
  return <section {...props} className="app-card app-stack">{children}</section>;
}

export function StatusTag({ status }) {
  const tone = status === "cita_confirmada" ? "positive" : status === "cancelado" ? "negative" : undefined;
  return <span className="app-badge" data-tone={tone}>{statuses[status] ?? "En trámite"}</span>;
}

export function ChannelTag({ channel }) {
  const [name, icon] = channels[channel] ?? ["Canal", "·"];
  return <span className="app-badge" data-tone={channel}><span aria-hidden="true">{icon}</span>{name}</span>;
}

export function ChatBubble({ children }) {
  return <p className="app-bubble">{children}</p>;
}

export function Table({ rows, label }) {
  return <table className="app-table" aria-label={label}><tbody>
    {rows.map(([title, value]) => <tr key={title}><th scope="row">{title}</th><td>{value}</td></tr>)}
  </tbody></table>;
}
