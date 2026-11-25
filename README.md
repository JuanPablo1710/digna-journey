# Motor de contexto omnicanal

Prototipo ficticio para Salud Digna. Incluye hasta S5: trámites, Web, identidad con OTP, WhatsApp, consola de Call Center y tablero de administración con SSE.

## Requisitos

- Python 3.11 o posterior
- Node.js 18 o posterior

## Configuración

Desde la raíz, copia `.env.example` a `.env`. Los valores incluidos son únicamente para desarrollo local y datos ficticios.

### Recrear SQLite después de los cambios de S1/S2

S1/S2 permiten valores `NULL` controlados en identidades y personas provisionales, y S2 agrega `mailbox_messages`. `create_all` no modifica restricciones de una base SQLite existente. Si `backend/data/app.db` fue creado antes de estos cambios, detén el backend y recréalo (se perderán únicamente los datos locales ficticios):

```powershell
Remove-Item -LiteralPath .\backend\data\app.db
```

Al volver a arrancar Uvicorn, las tablas y el seed mínimo se crean automáticamente.

## Backend

```powershell
cd backend
python -m pip install -r requirements.txt
uvicorn app.main:app --reload
```

La API queda disponible en `http://localhost:8000`; salud en `http://localhost:8000/health` y documentación en `http://localhost:8000/docs`.

## Frontend

En otra terminal:

```powershell
cd frontend
npm install
npm run dev
```

La aplicación queda disponible en `http://localhost:5173`. En `/web` se puede completar el flujo y recuperar un trámite por OTP; `/whatsapp` simula el canal conversacional y `/mailbox` muestra los correos simulados. Las rutas `/callcenter`, `/app`, `/admin` y `/login` permanecen reservadas para rebanadas posteriores.

## Prueba manual de S1

1. Abre `http://localhost:5173/web`.
2. Cotiza un estudio ficticio.
3. Completa el preregistro para ti o para otra persona.
4. Selecciona clínica y horario.
5. Confirma la cita y abre su línea de tiempo.

Para comprobar la reanudación, recarga la página después de elegir la clínica: mientras la cookie `web_session` siga vigente, el flujo vuelve directamente a la selección de horario.

Los endpoints públicos de catálogo y la documentación de la API están disponibles en `http://localhost:8000/docs`.

## Pruebas

### Prueba manual del tablero y actualizaciones en vivo

1. Abre `/login` e inicia sesión como `admin` con `Admin#2026`. En `/admin`, comprueba los totales, el embudo, los filtros y los recorridos.
2. Abre otra pestaña independiente e inicia sesión como asesor. Verifica a un solicitante y confirma una cita o agrega una nota. Observa el evento en el tablero y comprueba que se muestra enmascarado. Las notas internas aparecen solo en el contexto del asesor.
3. Interrumpe la conexión desde las herramientas de red del navegador. Comprueba **Reconectando...** y luego **Conectado** al volver a estar en línea.
4. Filtra la bitácora por tipo para revisar verificaciones, accesos denegados y consultas de contexto. En modo demo puedes completar el seed o reiniciar la base. Tras el reset vuelve a iniciar sesión.

### Preparar una demo limpia

Desde `backend`, con `DEMO_MODE=true`, ejecuta:

```powershell
python -m app.modules.demo.reset
```

El comando reconstruye la base configurada en `DATABASE_URL` y genera `docs/DEMO_DATA.md`. `POST /demo/reset` ejecuta el mismo proceso. Después del reset, vuelve a iniciar sesión y recarga los canales abiertos. La configuración de ejemplo usa dos minutos de bloqueo y quince minutos de abandono.

### Prueba manual de Call Center (S4)

1. Completa el flujo de Ana en Web y elige un horario en WhatsApp.
2. En `/login`, entra como `asesor` con `Asesor#2026`. En `/callcenter`, ingresa el teléfono de Ana y pulsa **Llamada entrante**. Deja el número vacío para probar una llamada oculta y busca por correo.
3. Selecciona la coincidencia enmascarada y verifica la fecha de nacimiento que registró Ana. Comprueba el solicitante, el paciente, el horario y la línea de tiempo. Agrega una nota interna y confirma la cita.
4. Pulsa **Terminar llamada**. El contexto se cierra y la verificación de esa llamada queda vencida.
5. Prueba tres fechas incorrectas y comprueba que se muestra el tiempo restante del bloqueo. `LOCKOUT_MINUTES` configura su duración (10 minutos por defecto).

Para probar la retoma por correo, inicia un agendamiento en `/whatsapp` con un número desconocido y detente después de capturar un correo ficticio. En `/web`, elige **Ya tengo un trámite**, solicita el código y léelo en `/mailbox`. Verifica el código y selecciona el borrador. El formulario Web conserva lo capturado y el borrador deja de estar disponible en el número de origen. También puedes recuperar un trámite semilla con `luis.demo@example.com`.

El buzón es público en modo demo y permite saber si se envió un correo. No existe en producción. Los borradores anteriores guardados solo en `session_state` no se migran. Para una demo desde cero, recrea SQLite con el procedimiento de configuración anterior.

```powershell
cd backend
pytest
```

## Credenciales ficticias

- Asesor: `asesor` / `Asesor#2026`
- Admin: `admin` / `Admin#2026`
- Paciente: correo ficticio + OTP obtenido en `/mailbox` (sin contraseña)

## Personas de demostración

- Luis Demo: `luis.demo@example.com`, `+522221111111`, nacimiento `1985-04-12`. Tiene un trámite abandonado en `clinica_elegida`.
- Marta Demo: `marta.demo@example.com`, `+522229999999`, nacimiento `1982-08-20`.
- Pablo Demo: `pablo.demo@example.com`, `+522229999999`, nacimiento `2012-03-15`.

Marta y Pablo comparten deliberadamente el mismo teléfono para probar la desambiguación por fecha de nacimiento.

## Cómo probar trámite para otra persona

1. En `/web`, elige **Ya tengo un trámite** y verifica `marta.demo@example.com` con el OTP del buzón. Selecciona el trámite de Marta.
2. Pulsa **Agendar para otra persona**, elige un estudio y revisa el aviso de privacidad. Conserva los datos de Marta como solicitante. Selecciona **Hijo o hija** y captura **Pablo Demo**, nacido el `15/03/2012`, como paciente. Guarda el trámite y elige una clínica.
3. En `/whatsapp`, selecciona el número compartido de Marta y Pablo. Dentro del chat elige **Retomar un trámite → Con mi correo**. Escribe el correo de Marta y su nuevo OTP. La lista debe distinguir los trámites para Marta y para Pablo. Elige el de Pablo y continúa con el horario.
4. Repite la retoma con `pablo.demo@example.com`. Pablo puede ver sus trámites propios del seed. El que creó Marta para él aparece en la lista de Marta.
5. Para probar la captura de un tercero desde WhatsApp, usa un número simulado libre y una variante ficticia como `marta.whatsapp@example.com`. Escribe «agendar», captura los datos de Marta y selecciona **Otra persona**. El chat muestra el aviso antes de pedir parentesco, nombre y fecha de nacimiento de Pablo.

## Prueba manual de identidad S2

1. Abre `http://localhost:5173/web` en una sesión nueva y elige **Ya tengo un trámite**.
2. Usa `luis.demo@example.com`.
3. Abre el enlace al buzón, copia el último OTP y vuelve a `/web`.
4. Confirma el código: la sesión rota y se muestra el trámite de Luis.
5. Para probar errores, introduce tres códigos incorrectos y observa los intentos restantes y el bloqueo temporal.

## Prueba manual de WhatsApp S3

1. En `/web`, crea a Ana con el teléfono `+522220000001` y el correo `ana.demo@example.com`, elige estudio y clínica, y detente antes del horario.
2. Abre `/whatsapp`, selecciona **Otro número**, escribe `+522220000001` e inicia la conversación.
3. Envía la fecha de nacimiento de Ana. El OTP se crea en `/mailbox` y el chat solo muestra el correo enmascarado.
4. Escribe el OTP, pulsa **Continuar** y elige un horario. El trámite cambia de `web` a `whatsapp` sin repetir datos.
5. Para probar interrupción, usa otro número, elige **Agendar cita**, contesta algunos campos y recarga: el motor pedirá exactamente el siguiente dato faltante.
6. **Reiniciar conversación** limpia solo el estado conversacional y vence la verificación de ese número; personas, trámites y eventos permanecen intactos.

