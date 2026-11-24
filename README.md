# Motor de contexto omnicanal

Prototipo ficticio para Salud Digna. Incluye hasta S3: núcleo de trámites, flujo web, identidad con OTP y canal conversacional simulado de WhatsApp.

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

## Prueba manual de identidad S2

1. Abre `http://localhost:5173/web` en una sesión nueva y elige **Ya tengo un trámite**.
2. Usa `luis.demo@example.com`.
3. Abre el enlace al buzón, copia el último OTP y vuelve a `/web`.
4. Confirma el código: la sesión rota y se muestra el trámite de Luis.
5. Para probar errores, introduce tres códigos incorrectos y observa los intentos restantes y el bloqueo temporal.

## Prueba manual de WhatsApp S3

1. En `/web`, crea a Ana con el teléfono `2221234567`, elige estudio y clínica, y detente antes del horario.
2. Abre `/whatsapp`, selecciona **Otro número**, escribe `2221234567` e inicia la conversación.
3. Envía la fecha de nacimiento de Ana. El OTP se crea en `/mailbox` y el chat solo muestra el correo enmascarado.
4. Escribe el OTP, pulsa **Continuar** y elige un horario. El trámite cambia de `web` a `whatsapp` sin repetir datos.
5. Para probar interrupción, usa otro número, elige **Agendar cita**, contesta algunos campos y recarga: el motor pedirá exactamente el siguiente dato faltante.
6. **Reiniciar conversación** limpia solo el estado conversacional y vence la verificación de ese número; personas, trámites y eventos permanecen intactos.

