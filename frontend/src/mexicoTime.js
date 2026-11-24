const timeZone = "America/Mexico_City";
const dateTime = new Intl.DateTimeFormat("es-MX", { timeZone, dateStyle: "medium", timeStyle: "short", hour12: false });
const time = new Intl.DateTimeFormat("es-MX", { timeZone, hour: "2-digit", minute: "2-digit", hourCycle: "h23" });

export function formatMexicoDateTime(value) {
  return dateTime.format(new Date(value));
}

export function formatMexicoTime(value) {
  return time.format(new Date(value));
}
