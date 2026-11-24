const API_URL = import.meta.env.VITE_API_URL ?? "";
const WEB_SESSION_KEY = "salud-digna-demo-web-session";
const WEB_CHANNEL_KEY = import.meta.env.VITE_CHANNEL_KEY_WEB ?? "demo-web-key";

function getWebSession() {
  let identifier = localStorage.getItem(WEB_SESSION_KEY);
  if (!identifier) {
    identifier = `web-${crypto.randomUUID()}`;
    localStorage.setItem(WEB_SESSION_KEY, identifier);
  }
  return identifier;
}

function resetWebSession() {
  const identifier = `web-${crypto.randomUUID()}`;
  localStorage.setItem(WEB_SESSION_KEY, identifier);
  return identifier;
}

async function request(path, options = {}) {
  const response = await fetch(`${API_URL}${path}`, {
    credentials: "include",
    ...options,
  });
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(body?.message ?? "No fue posible completar la solicitud.");
  }
  return body;
}

export async function getHealth() {
  return request("/health");
}

export async function getStudies() {
  return request("/catalog/studies");
}

export async function getClinics() {
  return request("/catalog/clinics");
}

export async function getSlots(clinicId) {
  return request(`/catalog/slots?clinic_id=${encodeURIComponent(clinicId)}`);
}

export async function sendWebInteraction(action, data = {}, idempotencyKey = crypto.randomUUID()) {
  return request("/channels/web/interactions", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Channel-Key": WEB_CHANNEL_KEY,
    },
    body: JSON.stringify({
      identifier: getWebSession(),
      identifier_type: "session",
      idempotency_key: idempotencyKey,
      kind: "action",
      action,
      content: null,
      data,
      timestamp: new Date().toISOString(),
    }),
  });
}

export async function continueWebCase() {
  const result = await sendWebInteraction("continue_case");
  if (result.reset_session) {
    resetWebSession();
  }
  return result;
}

export async function saveWebDraft(draft) {
  return sendWebInteraction("save_draft", draft);
}

export async function cancelWebCase(caseData = null) {
  const data = caseData
    ? { case_id: caseData.id, expected_version: caseData.version }
    : {};
  return sendWebInteraction("cancel_case", data);
}

export async function getCase(caseId) {
  return request(`/cases/${encodeURIComponent(caseId)}`);
}

export async function getCaseTimeline(caseId) {
  return request(`/cases/${encodeURIComponent(caseId)}/timeline`);
}

