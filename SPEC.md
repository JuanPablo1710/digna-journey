# SPEC.md — Motor de contexto omnicanal (Salud Digna · HackaTec 2026)

> Fuente de verdad del proyecto. Si algo no está aquí, **no lo inventes**: pregunta.
> Idioma: textos de interfaz y mensajes al usuario en **español**; identificadores de código, tablas y endpoints en **inglés**.

---

## 0. Cómo trabajar con este documento (instrucciones para Codex)

1. Construye **una rebanada (slice) a la vez**, en el orden de la sección 15. No avances a la siguiente hasta que la actual cumpla su "definición de terminado".
2. No cambies contratos de API, nombres de tablas ni eventos sin avisar y sin actualizar este archivo.
3. Cada rebanada incluye **pruebas automáticas** (pytest) del comportamiento nuevo.
4. Mantén las fronteras entre módulos (sección 2). Los canales **nunca** acceden a la base de datos ni al `patient_id`: solo hablan con la API.
5. Todo dato es **ficticio**. No integres servicios externos reales.
6. Prioridad absoluta: **estabilidad y repetibilidad de la demo** sobre cantidad de funciones.

---

## 1. Objetivo y alcance

**Problema.** Los canales de Salud Digna (web, app, WhatsApp, centro de contacto) funcionan aislados: el paciente repite datos y reinicia trámites.

**Solución.** Una capa central que (1) **reconoce y verifica** a la persona sin importar el canal, (2) **conserva el avance** del trámite, (3) registra una **línea de tiempo única** de eventos y (4) protege los datos con **roles, verificación escalonada y auditoría**.

**Cuatro pilares del reto:** Identidad · Contexto y estado · Trazabilidad · Seguridad.

**Demo objetivo (caso de Ana).** Web → WhatsApp → Centro de contacto (→ App opcional), sin repetir datos, con tres escenarios de resiliencia (sección 14).

**Fuera de alcance:** integración con servicios reales de Salud Digna, WhatsApp/telefonía reales, pagos, catálogo o agenda reales, IA obligatoria.

---

## 2. Stack y estructura del repositorio

| Capa | Tecnología |
|---|---|
| Backend | Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2.x, uvicorn |
| Base de datos | SQLite (archivo `backend/data/app.db`), acceso solo vía ORM (migrable a PostgreSQL) |
| Auth | JWT (PyJWT) para personal y pacientes con sesión; hash de contraseñas con bcrypt |
| Tiempo real | Server-Sent Events (SSE) |
| Frontend | React + Vite (JavaScript) + Tailwind, **una sola app con una ruta por canal** |
| Pruebas | pytest + httpx (TestClient) |

```
/
├── AGENTS.md
├── SPEC.md
├── README.md                  (instalación, credenciales por rol, pasos del demo)
├── .env.example
├── backend/
│   ├── requirements.txt
│   ├── data/                  (SQLite; ignorado por git)
│   ├── app/
│   │   ├── main.py            (FastAPI, CORS, routers)
│   │   ├── config.py          (variables de entorno)
│   │   ├── db.py              (engine, sesión)
│   │   ├── models.py          (tablas)
│   │   ├── schemas.py         (Pydantic)
│   │   ├── security.py        (JWT, hashing, permisos, enmascarado)
│   │   ├── catalog.py         (estudios, clínicas, horarios ficticios)
│   │   └── modules/
│   │       ├── adapters/      (web.py, whatsapp.py, callcenter.py, app.py → "interacción" canónica)
│   │       ├── identity/      (reconocer, verificar, nivel de confianza)
│   │       ├── cases/         (pasos, estado derivado, versión)
│   │       ├── events/        (registro inmutable, línea de tiempo, SSE)
│   │       ├── conversation/  (motor conversacional de WhatsApp)
│   │       ├── agent/         (consola del asesor)
│   │       ├── admin/         (tablero, auditoría)
│   │       └── demo/          (seed, reset, mailbox simulado)
│   └── tests/
├── frontend/
│   └── src/
│       ├── api.js             (cliente de la API; único punto de acceso al backend)
│       └── pages/             (Web, WhatsApp, CallCenter, App, Admin, Mailbox, Login)
└── docs/                      (diagramas, capturas)
```

**Reglas de arquitectura**

- Monolito modular: cada módulo expone funciones/servicios; los módulos no se importan en círculo.
- **Adaptadores** (`modules/adapters`): traducen la entrada de cada canal a una *interacción canónica* y la respuesta canónica al formato de ese canal. El núcleo (identity, cases, events) **no sabe de qué canal viene** la información.
- El estado actual del trámite se **deriva** de sus pasos; los eventos son **inmutables** (nunca UPDATE/DELETE sobre `events`).

---

## 3. Conceptos del dominio

- **Solicitante** vs **paciente.** Solicitante = quien contacta (escribe, llama, navega); paciente = a quien se le hará el estudio. Pueden ser la misma persona (`relationship = "self"`). La identidad que se reconoce y verifica es la del **solicitante**. Un solicitante puede tener varios trámites con pacientes distintos.
- **Reconocer** (buscar un identificador conocido) **≠ verificar** (probar que quien contacta es esa persona). Un teléfono reconocido **no** basta para mostrar datos.
- **Canal ≠ rol.** Canal = por dónde entra la persona (`web`, `whatsapp`, `callcenter`, `app`). Rol = qué puede ver/hacer (`paciente`, `asesor`, `admin`).
- **Regla:** no se verifica a alguien por el mismo medio que se quiere comprobar.

---

## 4. Modelo de datos

IDs: cadenas cortas legibles (`P-0001`, `C-0001`, `evt_...`). Fechas en UTC ISO-8601.

**persons**: `id`, `full_name`, `birth_date`, `email`, `phone` (E.164, normalizado), `is_provisional` (bool; true hasta la primera verificación exitosa), `created_at`.

**channel_identities**: `id`, `person_id`, `channel`, `identifier`, `identifier_type` (`session|phone|account`), `session_state` (JSON, estado conversacional), `last_seen_at`. Único (`channel`, `identifier`).

**verifications**: `id`, `person_id`, `channel`, `identifier`, `method` (`email_otp|dob_check|account_login|agent_assisted`), `code_hash`, `status` (`pending|succeeded|failed|expired|locked`), `attempts`, `expires_at` (OTP: 5 min), `valid_until` (tras éxito: 30 min), `created_at`.

**cases** (el trámite): `id`, `requester_id`, `patient_id`, `relationship` (`self|hijo_a|madre_padre|pareja|otro`), `study_id`, `clinic_id`, `slot_id`, `slot_datetime`, `steps` (JSON, ver sección 6), `status`, `abandoned` (bool), `current_channel`, `last_channel`, `version` (int, inicia en 1), `created_at`, `updated_at`.

**events**: `seq` (autoincremental), `event_id`, `type`, `case_id` (nullable), `person_id` (nullable), `channel`, `actor_role`, `actor_id`, `timestamp`, `payload` (JSON), `idempotency_key` (nullable, único).

**users** (acceso con credenciales o sesión): `id`, `username` (o email), `password_hash` (solo personal), `role` (`paciente|asesor|admin`), `person_id` (solo pacientes).

**notes**: `id`, `case_id`, `author_user_id`, `text`, `created_at`.

---

## 5. Reglas de identidad y nivel de confianza

### 5.1 Normalización
- Teléfonos a E.164 (país por defecto México `+52`). Correos en minúsculas. Fecha de nacimiento `YYYY-MM-DD` (la UI acepta DD/MM/AAAA).

### 5.2 Niveles de confianza (por canal/identificador)

| Nivel | Condición | Qué se puede mostrar |
|---|---|---|
| **0 · Desconocido** | Identificador sin persona asociada | Nada de datos personales ni de trámites. Se puede cotizar (información pública del catálogo). |
| **1 · Reconocido** | Identificador ligado a una persona, **sin** verificación vigente | Solo: "hay un trámite pendiente" (sin estudio, clínica ni datos). |
| **2 · Verificado** | Verificación exitosa con `valid_until` vigente | Detalle completo del trámite del solicitante. |

- **Confianza de origen:** la sesión que *creó* los datos (p. ej. la web donde se hizo el preregistro) tiene nivel 2 sobre **esos** trámites mientras dure la sesión (30 min desde la última actividad). Cualquier **otro canal** debe verificar.
- **Caducidad:** el nivel 2 expira a los 30 min (`valid_until`). Las acciones sensibles (confirmar, reagendar, cancelar, ver contexto) exigen nivel 2 vigente.

### 5.3 Reconocimiento
1. Buscar `channel_identities` por (`channel`, `identifier`).
2. Si no existe y el identificador es un teléfono: buscar `persons.phone`. Si hay **una** coincidencia → crear la identidad ligada (nivel 1). Si hay **varias** → estado `ambiguous`: pedir fecha de nacimiento para desambiguar antes de cualquier otra cosa. Si no hay → nivel 0 y se crea una persona provisional con ese teléfono.
3. Si el canal no trae teléfono (web/app), usar correo, o correo + fecha de nacimiento.
4. Solo coincidencia **exacta** (determinista). Nunca fusionar por nombre parecido.

### 5.4 Verificación

| Canal | Método |
|---|---|
| `web` / `app` | `account_login`: correo + código OTP enviado a ese correo (sin contraseña para pacientes) |
| `whatsapp` | `dob_check` (fecha de nacimiento debe coincidir) **y luego** `email_otp` al correo registrado (nunca por el propio WhatsApp) |
| `callcenter` | `agent_assisted`: el asesor valida un dato (fecha de nacimiento) y lo registra; o el paciente dicta un OTP enviado a su correo |

- OTP de 6 dígitos, expira en 5 min, **máximo 3 intentos**; al 3.º fallo: estado `locked` por 10 min y evento `verificacion_fallida` con `payload.locked = true`. Guardar solo el hash.
- Los correos se **simulan**: se guardan en un buzón de demo consultable en `GET /demo/mailbox?email=...` y en la página `/mailbox`. No se envía correo real.

### 5.5 Vinculación y fusión
- Al verificar con éxito, la persona deja de ser provisional (`is_provisional = false`) y se ligan sus identidades de canal. Si existían dos personas provisionales con los mismos datos exactos (teléfono + correo), se **fusionan** (evento `identidad_fusionada`) conservando el trámite más avanzado.

---

## 6. Trámite: pasos, estado, concurrencia, abandono

### 6.1 Pasos (`cases.steps`)
```json
{ "study": false, "patient_data": false, "clinic": false, "slot": false, "confirmed": false }
```
- `study`: hay estudio elegido. `patient_data`: paciente con nombre, fecha de nacimiento y parentesco completos (más correo y teléfono del solicitante). `clinic`, `slot`: elegidos. `confirmed`: cita confirmada.
- **Los pasos pueden completarse en cualquier orden.** El sistema siempre calcula `missing_steps` y los pide en el canal actual (esto resuelve la "información parcial").

### 6.2 Estado derivado (`status`)
```
cancelado        si fue cancelado
cita_confirmada  si confirmed
horario_propuesto si slot
clinica_elegida   si clinic
datos_completos   si patient_data
cotizando         en otro caso (con study elegido o no)
```
`abandoned` es un indicador **aparte** del progreso: se activa tras `ABANDON_MINUTES` sin actividad (config, por defecto 15; ajustable en demo) mediante una tarea periódica, y emite `tramite_abandonado`. No borra datos. Al volver a haber actividad verificada: `abandoned = false` y evento `tramite_reanudado`.

### 6.3 Concurrencia e idempotencia
- Toda escritura sobre un trámite envía `expected_version`. Si no coincide → **409 Conflict** con el trámite actual; el cliente decide. Cada escritura exitosa incrementa `version`.
- Toda interacción entrante lleva `idempotency_key`. Si ya existe en `events`, se devuelve la respuesta original **sin duplicar** eventos ni cambios.

### 6.4 Cambio de canal
Si llega actividad sobre un trámite por un canal distinto de `last_channel`: emitir `canal_cambiado` (payload: `from`, `to`), actualizar `last_channel` y `current_channel`.

---

## 7. Eventos (catálogo)

Estructura: `event_id, type, case_id, person_id, channel, actor{role,id}, timestamp, payload, idempotency_key`.

| Grupo | Tipos |
|---|---|
| Identidad | `contacto_creado`, `identidad_vinculada`, `verificacion_solicitada`, `verificacion_exitosa`, `verificacion_fallida`, `identidad_fusionada`, `consentimiento_aceptado` |
| Trámite | `tramite_creado`, `estudio_seleccionado`, `datos_paciente_capturados`, `clinica_seleccionada`, `horario_propuesto`, `cita_confirmada`, `cita_reagendada`, `tramite_cancelado`, `tramite_abandonado`, `tramite_reanudado` |
| Canal | `canal_iniciado`, `canal_cambiado`, `mensaje_recibido`, `mensaje_enviado`, `llamada_iniciada`, `llamada_finalizada` |
| Atención y auditoría | `nota_agregada`, `contexto_consultado`, `acceso_denegado` |

Reglas de emisión:
- Cada operación relevante emite su evento **en la misma transacción** que el cambio de estado.
- `contexto_consultado`: cuando un asesor obtiene el contexto de un paciente. `acceso_denegado`: cuando se rechaza un acceso por rol o por falta de verificación (con `payload.reason`).
- `consentimiento_aceptado`: primer contacto del solicitante (aviso de privacidad simulado), con canal y fecha.
- Cada evento publica una versión **enmascarada** por SSE (sección 8.8).

---

## 8. API

Convenciones: JSON; errores `{ "error": "codigo", "message": "texto en español" }`; respuestas 401/403/404/409/422 estándar. Documentación automática en `/docs`.

### 8.1 Autenticación
- `POST /auth/login` `{username, password}` → `{access_token, role, person_id?}` (asesor y admin).
- Pacientes: `POST /identity/verify/request` y `/confirm` con `channel="app"` o `"web"`; al confirmar devuelven JWT con rol `paciente` y `person_id`.

### 8.2 Catálogo (público, ficticio)
- `GET /catalog/studies`, `GET /catalog/clinics`, `GET /catalog/slots?clinic_id=`.

### 8.3 Interacciones de canal (entrada común)
`POST /channels/{channel}/interactions` · cabecera obligatoria `X-Channel-Key: <clave del canal>` (simula la firma de un webhook; claves en `.env`).

Solicitud (formato canónico):
```json
{
  "identifier": "+522221234567",
  "identifier_type": "phone",
  "idempotency_key": "wa-0001",
  "kind": "message",
  "action": null,
  "content": "hola",
  "data": {},
  "timestamp": "2026-11-24T16:00:00Z"
}
```
- `kind`: `message | action | call_started | call_ended`.
- `action` (cuando `kind=action`): `start_quote, start_booking, preregister, select_study, select_clinic, select_slot, confirm_case, cancel_case, continue_case, new_case, talk_to_agent`.

Respuesta:
```json
{
  "trust_level": 1,
  "case": { "...": "vista según nivel; con nivel < 2 solo {id, pending: true}" },
  "missing_steps": ["slot"],
  "messages": [
    { "text": "Hola, ...", "quick_replies": [ { "label": "Continuar", "action": "continue_case", "payload": {} } ] }
  ],
  "events": ["canal_cambiado", "identidad_vinculada"]
}
```

### 8.4 Identidad
- `POST /identity/verify/request` `{channel, identifier, method, birth_date?}` → crea verificación (OTP al buzón simulado).
- `POST /identity/verify/confirm` `{channel, identifier, code}` → `{trust_level, valid_until, access_token?}`.

### 8.5 Trámites
- `GET /cases/{id}` → según rol y nivel de confianza (sección 10).
- `PATCH /cases/{id}` `{expected_version, fields}` → actualiza pasos/campos (409 si hay conflicto).
- `GET /me/cases` (paciente con JWT).
- `GET /cases/{id}/timeline` → eventos del trámite en orden cronológico (paciente: versión simple; asesor: completa).

### 8.6 Asesor (rol `asesor`)
- `GET /agent/lookup?phone=|email=` → coincidencias (solo nombre enmascarado y nivel 1).
- `POST /agent/verify` `{person_id, method:"agent_assisted", birth_date}` → verificación asistida.
- `GET /agent/patients/{person_id}/context` → contexto completo + línea de tiempo. **Requiere verificación vigente**; si no → 403 + evento `acceso_denegado`. Si procede → evento `contexto_consultado`.
- `POST /agent/cases/{id}/notes` `{text}` → `nota_agregada`.
- Confirmar o avanzar el trámite: `PATCH /cases/{id}`.

### 8.7 Administrador (rol `admin`)
- `GET /admin/dashboard` → totales por estado, abandonados, **recuperados entre canales** (trámites con ≥ 2 canales distintos que avanzaron tras `canal_cambiado`), recorrido de canales por trámite, últimos eventos (enmascarados).
- `GET /admin/cases` (enmascarado), `GET /admin/audit` (`contexto_consultado`, `acceso_denegado`, `verificacion_*`).

### 8.8 Tiempo real
- `GET /stream?token=` (SSE). Mensajes `{type, case_id, channel, timestamp, summary}` con datos **enmascarados**. El asesor recibe además actualizaciones del trámite que tiene abierto.

### 8.9 Demo y salud
- `GET /health`.
- `POST /demo/reset` (borra y vuelve a cargar los datos semilla) y `POST /demo/seed`. Solo rol `admin` o `DEMO_MODE=true`.
- `GET /demo/mailbox?email=` (correos simulados con OTP). `POST /demo/cases/{id}/abandon` (fuerza el estado abandonado para la demo).

---

## 9. Motor conversacional (WhatsApp)

Reglas simples y deterministas (sin IA obligatoria). El estado se guarda en `channel_identities.session_state`; si el usuario se va y regresa, **se retoma donde se quedó**.

| Situación | Comportamiento |
|---|---|
| Nivel 0 | Saludo + opciones: *Cotizar estudio* / *Agendar cita*. Cotizar funciona sin datos (catálogo). |
| Agendar sin datos | Pide **solo lo que falta**, uno a uno: nombre completo, fecha de nacimiento (DD/MM/AAAA), correo, "¿para ti o para otra persona?" (si otra: parentesco, nombre y fecha de nacimiento del paciente). |
| Nivel 1 (teléfono reconocido) | "Hola {nombre}. Tienes un trámite pendiente. Para continuar necesito verificar que eres tú. ¿Cuál es tu fecha de nacimiento?" → si coincide, envía OTP al correo registrado (mostrar correo enmascarado) → espera el código. |
| Verificación fallida | Mensaje claro; 3 intentos máximo y bloqueo temporal. |
| Nivel 2 | Resume el trámite ("ultrasonido en Clínica X; falta: horario") y ofrece *Continuar / Empezar otro trámite / Hablar con un asesor*. Ofrece horarios como respuestas rápidas. |
| Ambigüedad (varias personas con el mismo teléfono) | Pide fecha de nacimiento para desambiguar; nunca muestra datos antes. |
| Texto no entendido | "No te entendí. Elige una opción:" + respuestas rápidas. |

Comprensión de texto: coincidencia por palabras clave (`hola`, `cotizar`, `agendar`, `continuar`, `asesor`, `cancelar`). Un resumen o interpretación con IA es **opcional** y debe estar detrás de la variable `AI_ENABLED` con respaldo por plantilla.

---

## 10. Roles, permisos y enmascarado

| Recurso / acción | Paciente | Asesor | Admin |
|---|---|---|---|
| Ver su propio trámite y línea de tiempo simple | Sí (nivel 2) | — | — |
| Ver contexto completo de un paciente | No | Sí, **solo con verificación vigente** (queda auditado) | No (solo enmascarado) |
| Avanzar / confirmar trámite | Sí (el suyo, nivel 2) | Sí (paciente verificado) | No |
| Agregar notas internas | No | Sí | No |
| Tablero y métricas | No | No | Sí |
| Auditoría | No | No | Sí |
| Reset / seed de la demo | No | No | Sí |

**Enmascarado** (función única en `security.py`, usada por admin y por el SSE):
- Nombre: `A*** M.` · Teléfono: `***4821` · Correo: `a***@dominio.com` · Fecha de nacimiento: no se muestra.

Cada denegación por rol o falta de verificación → evento `acceso_denegado`.

---

## 11. Interfaces (frontend)

Una app React; **cada ruta es un cliente independiente que solo usa `src/api.js`** (no conoce `patient_id` ni la base de datos; usa el identificador propio de su canal).

| Ruta | Qué simula | Contenido |
|---|---|---|
| `/web` | Sitio web | Cotizador (estudio → precio demo) → agendar → formulario de preregistro (nombre, fecha de nacimiento, correo, teléfono, ¿para quién?) → clínica → horario → confirmar. La sesión del navegador es el identificador. Se puede cerrar a mitad. |
| `/whatsapp` | WhatsApp | Marco de teléfono con burbujas y respuestas rápidas. Campo para elegir el **número de teléfono simulado**. Envía interacciones y pinta las respuestas. Enlace al buzón. |
| `/callcenter` | Centro de contacto | Login de asesor. "Softphone": ingresar número y **simular llamada entrante** → búsqueda; botón de verificación asistida; panel con contexto, línea de tiempo y acciones (confirmar, agregar nota). Se actualiza en vivo. |
| `/app` | App móvil | Marco de teléfono. Login por correo + OTP. Muestra "Mis trámites", progreso y cita confirmada. Opcional: reagendar. |
| `/admin` | Tablero | Login de admin. KPIs, tabla de trámites enmascarada con el recorrido de canales, feed de eventos en vivo, bitácora de auditoría, botones de reset/seed. |
| `/mailbox` | Correo simulado | Bandeja pública de demo con los OTP enviados. |

Requisitos de UI: textos en español; estados de carga y error visibles; diseño sobrio y legible; funcionar en el celular (WhatsApp y App); el tablero debe mostrar claramente **por qué canales pasó cada trámite**.

---

## 12. Datos de demo (seed) y credenciales

Catálogo ficticio: 5 estudios (con instrucciones de preparación ficticias), 3 clínicas ("Clínica Puebla Centro (demo)", "Clínica Puebla Angelópolis (demo)", "Clínica Cholula (demo)"), horarios generados para los próximos 3 días entre 09:00 y 13:00 cada hora.

Personas semilla (todas ficticias, correos `@example.com`):
- **Ana Demo**: **no existe** al inicio (el demo la crea desde la web).
- **Luis Demo**: trámite en `clinica_elegida`, marcado como abandonado.
- **Marta Demo** y su hijo **Pablo Demo**: comparten el mismo teléfono (caso de ambigüedad).
- Algunos trámites en estados variados para poblar el tablero.

Credenciales de prueba (documentar en README):
- Asesor: `asesor` / `Asesor#2026`
- Admin: `admin` / `Admin#2026`
- Paciente: correo ficticio + código OTP obtenido en `/mailbox` (no hay contraseña).

---

## 13. Seguridad y configuración

- `.env` (no se sube a git): `JWT_SECRET`, `CHANNEL_KEY_WEB`, `CHANNEL_KEY_WHATSAPP`, `CHANNEL_KEY_CALLCENTER`, `CHANNEL_KEY_APP`, `DATABASE_URL`, `ABANDON_MINUTES`, `DEMO_MODE`, `AI_ENABLED`. Proveer `.env.example`.
- Contraseñas con bcrypt; OTP solo como hash; JWT con expiración (8 h).
- CORS limitado al origen del frontend.
- Permisos verificados **en el backend** para cada endpoint (no solo ocultar botones).
- Nunca registrar datos personales completos en logs.
- Aviso de privacidad y consentimiento simulados en el primer contacto (evento `consentimiento_aceptado`).

---

## 14. Pruebas de aceptación (pytest)

Deben existir y pasar:
1. `test_ana_full_flow`: Web (preregistro + clínica) → WhatsApp (reconoce, dob, OTP, elige horario) → Callcenter (verificación asistida, confirma) → App (ve cita confirmada). Verifica estados, `canal_cambiado` y la línea de tiempo.
2. `test_interruption_resume`: abandonar a mitad de WhatsApp y regresar retoma el paso exacto.
3. `test_partial_info_prompts_missing`: con datos incompletos, el sistema pide **solo** lo que falta.
4. `test_unknown_number_no_data`: número desconocido → no se muestran datos.
5. `test_shared_phone_disambiguation`: dos personas con el mismo teléfono → pide fecha de nacimiento y no adivina.
6. `test_idempotency_duplicate_interaction`: misma `idempotency_key` no duplica eventos.
7. `test_version_conflict`: `expected_version` viejo → 409.
8. `test_otp_expiry_and_lockout`: OTP expirado y bloqueo tras 3 fallos.
9. `test_rbac_matrix`: cada rol solo accede a lo permitido (sección 10).
10. `test_admin_masking`: el admin nunca recibe datos sin enmascarar.
11. `test_agent_access_requires_verification_and_audits`: sin verificación → 403 + `acceso_denegado`; con verificación → `contexto_consultado`.

Escenarios de resiliencia de la demo: **interrupción**, **información parcial** e **identidad no reconocida**.

---

## 15. Orden de construcción (rebanadas)

Cada rebanada termina con pruebas verdes y el backend/frontend arrancando sin errores.

| Rebanada | Contenido | Definición de terminado |
|---|---|---|
| **S0 · Esqueleto** | Estructura de carpetas, FastAPI con `/health`, modelos y creación de tablas, seed básico, frontend con rutas vacías, `.env.example`, README inicial | `uvicorn` y `npm run dev` arrancan; `/health` responde; pytest corre |
| **S1 · Núcleo + Web** | persons, cases, events; endpoint de interacciones para `web` (preregistro, estudio, clínica, horario); estado derivado; timeline; idempotencia y versión | Se puede crear un trámite desde `/web` y ver su línea de tiempo en la API |
| **S2 · Identidad** | Niveles de confianza, reconocimiento, OTP, `dob_check`, buzón simulado, bloqueo, vigencia | Pruebas 4, 5, 8 verdes |
| **S3 · WhatsApp** | Adaptador, motor conversacional, simulador `/whatsapp` | Se retoma desde WhatsApp el trámite hecho en la web (prueba 2 y 3) |
| **S4 · Roles + Call Center** | Login, permisos, adaptador callcenter, consola del asesor, notas, auditoría | Pruebas 9 y 11 verdes; Ana se confirma desde `/callcenter` |
| **S5 · Admin + tiempo real** | Tablero, enmascarado, SSE, auditoría | Prueba 10 verde; el tablero se actualiza en vivo |
| **S6 · App + pulido** | `/app` (OTP), reagendar opcional, reset/seed, README con credenciales, `test_ana_full_flow` completo | Demo completa repetible con un clic de reset |

**Decisiones de recorte:** si al terminar S5 hay poco tiempo, la App (S6) se recorta; lo demás **no**.

---

## 16. Fuera de alcance (no construir)

Integraciones reales, pagos, catálogo/agenda reales, microservicios, colas de mensajes, IA como requisito, múltiples idiomas, registro/administración de usuarios por interfaz.
