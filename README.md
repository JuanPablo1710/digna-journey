# Motor de contexto omnicanal

Prototipo ficticio para Salud Digna. La rebanada S1 incluye el núcleo de trámites y el flujo web de cotización, preregistro, clínica, horario y confirmación.

## Requisitos

- Python 3.11 o posterior
- Node.js 18 o posterior

## Configuración

Desde la raíz, copia `.env.example` a `.env`. Los valores incluidos son únicamente para desarrollo local y datos ficticios.

### Recrear SQLite después del cambio de borradores

S1 permite que `channel_identities.person_id` sea `NULL` mientras una sesión solo contiene un borrador. `create_all` no modifica restricciones de una base SQLite existente. Si `backend/data/app.db` fue creado antes de este cambio, detén el backend y recréalo (se perderán únicamente los datos locales ficticios):

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

La aplicación queda disponible en `http://localhost:5173`. En `/web` se puede completar el flujo S1. Las rutas `/whatsapp`, `/callcenter`, `/app`, `/admin`, `/mailbox` y `/login` permanecen como páginas vacías para rebanadas posteriores.

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
- Paciente: correo ficticio + OTP (se implementará en una rebanada posterior)

