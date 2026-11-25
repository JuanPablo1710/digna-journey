# Memoria de datos de Digna Journey

Inventario del código ejecutable. Las rutas se extrajeron de `GET /openapi.json` en modo demo y los permisos se cotejaron con los routers y servicios. Las tablas provienen de `Base.metadata` de SQLAlchemy, los eventos de los emisores y su catálogo de presentación, y las pruebas de `python -m pytest --collect-only`. El [README](../README.md#datos-y-credenciales-de-demostración) es la referencia para las credenciales de demostración.

## 1. Rutas de la API

**31 operaciones sobre 29 rutas** con `DEMO_MODE=true`. «Público» indica que la ruta no exige un JWT de rol. Las claves de canal, cookies y pruebas de identidad que correspondan se indican en la tabla.

| Método | Ruta exacta | Acceso efectivo | Descripción |
|---|---|---|---|
| GET | `/catalog/studies` | Público | Lista estudios, precios y preparación ficticia. |
| GET | `/catalog/clinics` | Público | Lista clínicas ficticias. |
| GET | `/catalog/slots` | Público | Devuelve horarios de una clínica por `clinic_id`. |
| POST | `/channels/web/interactions` | Paciente o visitante Web con `X-Channel-Key`. Las acciones protegidas exigen sesión Web y el nivel correspondiente. | Cotización, borrador, preregistro, retoma, selección, confirmación y cancelación. |
| GET | `/cases/{case_id}` | Paciente mediante cookie `web_session` vinculada. | Devuelve detalle con nivel 2, solo ID y pendiente con nivel 1, o denegación con nivel 0. |
| PATCH | `/cases/{case_id}` | Asesor con Bearer y verificación vigente del solicitante. | Avanza o confirma el trámite con versión. |
| GET | `/cases/{case_id}/timeline` | Paciente con cookie Web y nivel 2. | Devuelve la línea de tiempo Web y omite los eventos de notas internas. |
| POST | `/channels/whatsapp/interactions` | Paciente o visitante del chat con `X-Channel-Key` y número. Detalle y cambios protegidos sujetos al nivel o a una retoma verificada. | Mensajes, respuestas rápidas, retoma y agendamiento simulado. |
| GET | `/me/cases` | Paciente con Bearer de App vigente y `X-Channel-Key`. | Lista los trámites donde la cuenta es solicitante o paciente y renueva la sesión. |
| POST | `/channels/app/interactions` | Paciente con Bearer de App vigente y `X-Channel-Key`. Para un folio existente comprueba pertenencia. | Abre, crea, avanza o confirma trámites y renueva la sesión. |
| POST | `/identity/verify/request` | Flujo de paciente, sin JWT de rol. Web requiere cookie válida, App requiere clave de canal y el OTP de WhatsApp exige fecha ya validada. | Inicia OTP o comprueba fecha de nacimiento según el método. |
| POST | `/identity/verify/confirm` | Flujo de paciente con OTP. Web requiere cookie válida y App requiere clave de canal. | Valida el código, concede nivel 2 y emite token de paciente. |
| POST | `/auth/login` | Entrada pública para credenciales de asesor o administrador. | Emite el JWT de personal con rol. |
| GET | `/admin/dashboard` | Administrador con Bearer. | Métricas, embudo, recorridos y eventos recientes enmascarados. |
| GET | `/admin/cases` | Administrador con Bearer. | Lista trámites enmascarados y admite filtro de estado y canal. |
| GET | `/admin/audit` | Administrador con Bearer. | Bitácora de consultas de contexto, accesos denegados y verificaciones. |
| GET | `/agent/lookup` | Asesor con Bearer. | Busca por teléfono o correo y devuelve nombre enmascarado, ID de persona y nivel 1. |
| POST | `/agent/verify` | Asesor con Bearer. | Verifica al solicitante por fecha de nacimiento y vincula la llamada cuando corresponde. |
| GET | `/agent/patients/{person_id}/context` | Asesor con Bearer y verificación vigente de ese solicitante. | Devuelve trámites solicitados, datos del paciente, línea de tiempo y notas. Registra la consulta. |
| POST | `/agent/cases/{case_id}/notes` | Asesor con Bearer y verificación vigente del solicitante. | Agrega una nota interna. |
| POST | `/channels/callcenter/interactions` | Asesor con Bearer y `X-Channel-Key`. | Inicia o termina llamadas simuladas del asesor. |
| POST | `/resume/request` | Visitante o paciente de Web o WhatsApp. WhatsApp requiere clave de canal y teléfono como destino. | Inicia retoma por correo, devuelve una respuesta neutra 202 y establece una cookie de sesión. |
| POST | `/resume/confirm` | Paciente con la cookie del desafío y el OTP. | Verifica el correo y devuelve trámites o borradores disponibles para esa retoma. |
| POST | `/resume/select` | Paciente con la cookie y el desafío ya verificado y vigente. | Elige un trámite o transfiere un borrador mediante versión e idempotencia. |
| GET | `/demo/mailbox` | Público cuando `DEMO_MODE=true`. | Lista mensajes y OTP ficticios de un correo. |
| POST | `/demo/reset` | Público cuando `DEMO_MODE=true`. | Reconstruye SQLite, repone el seed e invalida sesiones previas. |
| GET | `/stream` | Administrador o asesor con Bearer. El asesor necesita verificación vigente. | SSE enmascarado. El asesor puede limitarlo por `case_id`. |
| POST | `/demo/seed` | Administrador con Bearer y `DEMO_MODE=true`. | Completa las filas semilla que falten. |
| GET | `/demo/new-device` | Público cuando `DEMO_MODE=true`. | Devuelve 204 para habilitar la opción de simulación. |
| POST | `/demo/new-device` | Público cuando `DEMO_MODE=true`. Usa la cookie si existe. | Invalida la sesión Web actual y elimina su cookie. |
| GET | `/health` | Público | Devuelve el estado `ok`. |

Con el modo demo desactivado, OpenAPI omite `POST /demo/seed` y ambos métodos de `/demo/new-device`. `/demo/mailbox` y `/demo/reset` siguen registrados y devuelven 403. Las páginas de React y las rutas automáticas `/docs`, `/redoc` y `/openapi.json` quedan fuera del inventario de operaciones de OpenAPI.

## 2. Tablas y relaciones

El nombre exacto de la tabla de usuarios es **`users`**, en plural. El modelo declara **10 tablas, 87 columnas y 11 claves foráneas**.

| Tabla | PK | FK | Resto de columnas |
|---|---|---|---|
| `persons` | `id` | — | `full_name`, `birth_date`, `email`, `phone`, `is_provisional`, `created_at`. |
| `channel_identities` | `id` | `person_id → persons.id` (opcional) | `channel`, `identifier`, `identifier_type`, `session_state`, `last_seen_at`. Unicidad de `(channel, identifier)`. |
| `drafts` | `id` | `identity_id → channel_identities.id` (única), `requester_id → persons.id` (opcional) | `email`, `data`, `version`, `updated_at`, `expires_at`. |
| `resume_challenges` | `id` | — | `email`, `channel`, `destination`, `code_hash`, `attempts`, `expires_at`, `locked_until`, `valid_until`, `scope`, `selections`. |
| `verifications` | `id` | `person_id → persons.id` | `channel`, `identifier`, `method`, `code_hash`, `status`, `attempts`, `expires_at`, `valid_until`, `created_at`. |
| `cases` | `id` | `requester_id → persons.id`, `patient_id → persons.id` | `relationship`, `study_id`, `clinic_id`, `slot_id`, `slot_datetime`, `steps`, `status`, `abandoned`, `current_channel`, `last_channel`, `version`, `created_at`, `updated_at`. |
| `events` | `seq` (autoincremental) | `case_id → cases.id` y `person_id → persons.id` (ambas opcionales) | `event_id` (única), `type`, `channel`, `actor_role`, `actor_id`, `timestamp`, `payload`, `idempotency_key` (única cuando tiene valor). |
| `users` | `id` | `person_id → persons.id` (opcional) | `username` (única), `password_hash`, `role`. |
| `notes` | `id` | `case_id → cases.id`, `author_user_id → users.id` | `text`, `created_at`. |
| `mailbox_messages` | `id` | — | `email`, `subject`, `body`, `code`, `created_at`. El código se entrega en claro solo en el buzón simulado. |

- Una persona puede tener muchas identidades de canal, verificaciones, cuentas de usuario y borradores. Cada identidad tiene como máximo un borrador. Una identidad, una cuenta o un borrador pueden carecer del vínculo opcional a una persona.
- Cada trámite tiene dos vínculos obligatorios a `persons`, uno para el solicitante y otro para el paciente. Pueden apuntar a la misma persona.
- Un trámite tiene muchas notas y eventos. Cada nota tiene un autor en `users`. Un evento puede apuntar a una persona y a un trámite, y admite ambos vínculos vacíos.
- El correo vincula búsquedas de retoma y buzón sin FK. El catálogo de estudios, clínicas y horarios se define en código. `events.actor_id` se guarda como texto y las llamadas se correlacionan con `call_id` en los eventos. Consulta el [diagrama ER](ARCHITECTURE.md#modelo-de-datos).

## 3. Tipos de evento

El catálogo de presentación en `modules/events/safe.py` contiene **26 etiquetas**. Las categorías siguientes agrupan los tipos por función.

| Categoría | Tipos |
|---|---|
| Identidad, consentimiento y verificación | `contacto_creado`, `consentimiento_aceptado`, `identidad_vinculada`, `identidad_fusionada`, `verificacion_solicitada`, `verificacion_exitosa`, `verificacion_fallida`. |
| Trámite y agenda | `tramite_creado`, `estudio_seleccionado`, `datos_paciente_capturados`, `clinica_seleccionada`, `horario_propuesto`, `cita_confirmada`, `cita_reagendada`, `tramite_cancelado`, `tramite_abandonado`, `tramite_reanudado`. |
| Canal, chat y llamadas | `canal_iniciado`, `canal_cambiado`, `mensaje_recibido`, `mensaje_enviado`, `llamada_iniciada`, `llamada_finalizada`. |
| Atención y auditoría | `nota_agregada`, `contexto_consultado`, `acceso_denegado`. |

`tramite_abandonado` se genera en el seed histórico. `tramite_reanudado` puede emitirse al seleccionar una retoma autorizada. `cita_reagendada` tiene etiqueta pero carece de emisor. `actividad_registrada` es el tipo sustituto de la vista enmascarada ante un evento desconocido, no un tipo que guarde una operación del prototipo.

## 4. Roles y enmascarado

| Operación | Paciente | Asesor (`asesor`) | Administrador (`admin`) |
|---|---|---|---|
| Consultar un trámite y su historia | Web autoriza por cookie del solicitante con nivel 2. App lista y permite abrir sus trámites como solicitante o paciente. WhatsApp y retoma aplican su propia verificación o confianza de origen. | Consulta el contexto de los trámites del solicitante con verificación vigente del propio asesor. | Consulta el listado enmascarado, los recorridos y los eventos de Admin. |
| Modificar trámites | Sí, por las acciones habilitadas de cada canal y con versión. App acepta solicitante o paciente. | Sí, mediante `PATCH /cases/{case_id}` con verificación vigente del solicitante. | Sin permiso de modificación clínica o de agenda. |
| Consultar contexto completo y notas internas | Sin permiso de contexto de asesor. | Sí, con verificación del solicitante. Puede agregar notas y la consulta queda auditada. | Sin permiso de contexto completo. |
| Gestionar llamada simulada | Sin acceso al adaptador de Call Center. | Puede iniciar, verificar y terminar sus llamadas. Al terminar la llamada vence su autorización asociada. | Sin acceso al adaptador de Call Center. |
| Métricas, bitácora y SSE | Sin acceso a Admin ni SSE. | Sin acceso a Admin. SSE limitado a trámites de solicitantes con autorización vigente. | Tablero, bitácora y SSE enmascarados. |
| Reset, seed y buzón | El reset y el buzón son públicos en modo demo. | El reset y el buzón están disponibles en modo demo. | Además, puede completar el seed por API en modo demo. |

- **Reconocimiento**. En la búsqueda del asesor, la API devuelve nombre enmascarado y nivel 1. El detalle se habilita con verificación asistida. Web con nivel 1 solo ve el ID y el indicador pendiente. En WhatsApp el saludo de número reconocido puede usar el nombre antes de verificar el trámite.
- **Admin**. En el listado y la bitácora, `masked_person` reduce el nombre a iniciales enmascaradas como `A*** D.`, el teléfono a sus últimos cuatro dígitos como `***0001` y el correo a inicial más dominio como `a***@example.com`. La vista omite fecha de nacimiento, códigos y texto de notas. La bitácora revela el ID del actor solo si corresponde a personal registrado.
- **SSE**. El mismo serializador seguro emite tipo, folio, canal, fecha y resumen. El resumen puede incluir solo el nombre enmascarado si dispone de la persona. El evento SSE omite el payload interno.
- **Vistas de paciente**. App devuelve un resumen con nombre del paciente cuando es un trámite para otra persona, sin ID interno de persona ni fecha de nacimiento. La vista Web autorizada incluye datos de solicitante y paciente. Los historiales excluyen el texto de notas internas y las claves privadas de eventos.

## 5. Credenciales y datos semilla

Credenciales ficticias tal como figuran en el README.

| Rol y persona | Correo o usuario | Contraseña o acceso | Teléfono | Nacimiento |
|---|---|---|---|---|
| Paciente · Ana Demo | `ana.demo@example.com` | Acceso por OTP | `+522220000001` | `1990-05-10` |
| Paciente · Marta Demo | `marta.demo@example.com` | Acceso por OTP | `+522229999999` | `1982-08-20` |
| Asesor | `asesor` | `Asesor#2026` | — | — |
| Administrador | `admin` | `Admin#2026` | — | — |

Para App, solicita el código con el correo y abre [`/mailbox`](http://localhost:5173/mailbox) en modo demo para consultar el mensaje más reciente. Para WhatsApp, valida primero la fecha de nacimiento. Cada OTP se genera al solicitarlo.

| Persona | ID de seed | Correo | Teléfono | Nacimiento y relación con la demo |
|---|---|---|---|---|
| Ana Demo | — | `ana.demo@example.com` | `+522220000001` | `1990-05-10`. El README da estos datos para el alta. El seed deja libres su correo y teléfono. |
| Marta Demo | `P-1002` | `marta.demo@example.com` | `+522229999999` | `1982-08-20`. Solicitante de C-1002. |
| Pablo Demo | `P-1003` | `pablo.demo@example.com` | `+522229999999` | `2012-03-15`. Paciente de C-1002 y solicitante de C-1003. Comparte teléfono con Marta. |
| Bruno Demo | `P-1007` | `bruno.demo@example.com` | `+522220000007` | `1987-02-17`. C-1007 está confirmado y recorrió Web → WhatsApp → Call Center. |

| Folio | Solicitante → paciente | Estudio | Clínica | Estado, abandono y recorrido |
|---|---|---|---|---|
| `C-1001` | Luis Demo (`P-1001`) → Luis Demo | `ST-003` Ultrasonido abdominal | `CL-001` Clínica Puebla Centro (demo) | `clinica_elegida`, abandonado, Web, sin horario. |
| `C-1002` | Marta Demo → Pablo Demo (`hijo_a`) | `ST-001` Biometría hemática | `CL-002` Clínica Puebla Angelópolis (demo) | `horario_propuesto`, activo, Web → WhatsApp. El horario se calcula al sembrar. |

## 6. Pruebas y árbol del repositorio

`python -m pytest --collect-only -q` recopila **83 pruebas** desde `backend`.

| Archivo | Pruebas | Área |
|---|---:|---|
| `test_admin.py` | 5 | Métricas de recuperación, historial semilla, enmascarado, permisos y seed. |
| `test_agent.py` | 5 | Roles, verificación asistida, llamadas ocultas, intentos compartidos y contexto. |
| `test_app.py` | 6 | Recorrido completo de Ana, pertenencia, versión, terceros, renovación y OpenAPI. |
| `test_catalog_time.py` | 1 | Calendario de Ciudad de México y serialización UTC. |
| `test_demo_device.py` | 2 | Invalidación de cookie y ausencia de rutas fuera de demo. |
| `test_demo_reset.py` | 3 | Reset, seed, limpieza e invalidación de sesiones. |
| `test_health.py` | 1 | Disponibilidad de la API. |
| `test_identity.py` | 14 | Reconocimiento, ambigüedad, OTP, intentos, caducidad y fusión exacta. |
| `test_resume.py` | 7 | Retoma por correo, alcance, OTP y transferencia concurrente de borradores. |
| `test_staff_auth.py` | 2 | Credenciales semilla, JWT y búsqueda de asesor. |
| `test_stream.py` | 5 | Autorización, enmascarado SSE, reanudación, caducidad y 24 conexiones concurrentes. |
| `test_web_core.py` | 19 | Catálogo, sesiones, borradores, estado, versiones, cancelación e idempotencia. |
| `test_whatsapp.py` | 13 | Conversación, captura parcial, ambigüedad, confianza de origen, privacidad e idempotencia. |

Árbol a dos niveles. Se omiten bases locales, entornos virtuales, dependencias instaladas y archivos `.gitkeep`.

```text
.
├── .env.example
├── .gitignore
├── AGENTS.md
├── DEMO.md
├── README.md
├── SPEC.md
├── backend
│   ├── app/
│   ├── data/
│   ├── pytest.ini
│   ├── requirements.txt
│   └── tests/
├── docs
│   ├── ARCHITECTURE.md
│   ├── DEMO_DATA.md
│   ├── DEMO_PARA_PEGAR.md
│   ├── DEPLOYMENT.md
│   └── MEMORIA_DATOS.md
└── frontend
    ├── index.html
    ├── package-lock.json
    ├── package.json
    ├── postcss.config.js
    ├── public/
    ├── src/
    ├── tailwind.config.js
    ├── tests/
    └── vite.config.js
```

## 7. Funciones consultadas

| Función | Estado en el código |
|---|---|
| `PATCH /cases/{id}` | **Implementada** como `PATCH /cases/{case_id}`. Exige token de asesor, verificación vigente del solicitante y `expected_version`. Admite `fields.study_id`, `clinic_id`, `slot_id` y `confirmed: true`. |
| Retoma por folio público `public_ref` | **No implementada**. El modelo carece de `public_ref`. La interfaz usa `cases.id` como folio. `/resume/select` acepta un ID incluido en el alcance de un desafío ya verificado. |
| Retoma por teléfono más fecha de nacimiento | **No implementada como vía de retoma**. La solicitud de retoma exige correo. El teléfono identifica el destino de WhatsApp. El chat sí usa número y fecha para reconocimiento y desambiguación, seguido del OTP por correo. |
| Verificación asistida con OTP opcional | **No implementada** en Call Center. `/agent/verify` acepta `agent_assisted` con fecha obligatoria. El OTP genérico de identidad no crea la autorización de asesor o llamada que exige el contexto. |

## Diferencias entre SPEC.md y el código

| Tema | Diferencia observada |
|---|---|
| Abandono y ruta de demo (§6.2 y §8.9) | El seed trae casos abandonados y la retoma por correo puede reactivarlos. El código carece de tarea periódica de abandono y de `POST /demo/cases/{id}/abandon`. |
| OTP asistido (§5.4) | La opción de dictar un código al asesor figura en el SPEC. El endpoint real de asesor verifica por fecha de nacimiento. |
| Reagendado (§7) | `cita_reagendada` está catalogado y tiene etiqueta de presentación. Carece de emisor y de flujo de reagendado. |
| Permisos de reset (§10) | La matriz del SPEC agrupa reset y seed bajo admin. Solo el seed exige rol de administrador. El reset HTTP es público en modo demo. |
| Línea de tiempo del asesor (§8.5 y §8.6) | El GET directo de la línea de tiempo aplica la cookie Web. El asesor obtiene la vista completa desde `/agent/patients/{person_id}/context`, no desde el GET directo. |
| Estado y almacenamiento del borrador (§4 y §6.5) | La información del borrador se guarda en `drafts`. La identidad conserva metadatos de sesión en `session_state`. `channel_identities.person_id` también puede quedar vacío al invalidar o rotar una sesión. |
| Respuesta inicial de WhatsApp (§5.2 y §9) | La tabla de confianza limita el nivel 1 al aviso de trámite pendiente. El adaptador puede saludar con el nombre en ese nivel, como describe §9. |
| Respuestas idempotentes (§6.3) | Web guarda instantáneas internas. App evita repetir la mutación y devuelve el estado y la línea de tiempo consultados al procesar el reintento, que pueden incluir actividad posterior. |
| Payload interno e idempotencia (§9) | Los mensajes guardan un tipo que clasifica la entrada. Algunos eventos también contienen una instantánea privada `_response` para idempotencia. Si incluye una vista autorizada del trámite, puede llevar datos como la fecha de nacimiento guardada de sus personas. Los serializadores públicos omiten esa clave. |
| Inmutabilidad de eventos (§2 y §7) | WhatsApp hace `flush` de `mensaje_recibido` y después completa su payload privado en la misma transacción. El evento queda finalizado antes del commit, aunque esa escritura puede generar un UPDATE sobre la fila recién insertada. |
| Formato de errores (§8) | Los errores de dominio llevan `error` y `message`. Los fallos de validación automática de FastAPI devuelven `detail`. |
| Folio público y retoma alternativa | El SPEC vigente documenta la retoma por correo y el uso del ID como folio. El código coincide en esos puntos. `public_ref` y la solicitud de retoma por teléfono más fecha quedan pendientes como funciones distintas del reconocimiento de WhatsApp. |
