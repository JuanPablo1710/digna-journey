# Motor de contexto omnicanal

Esqueleto (S0) del prototipo ficticio para Salud Digna. Incluye FastAPI, SQLite con SQLAlchemy, el catálogo de demostración y una app React con una ruta vacía por canal.

## Requisitos

- Python 3.11 o posterior
- Node.js 18 o posterior

## Configuración

Desde la raíz, copia `.env.example` a `.env`. Los valores incluidos son únicamente para desarrollo local y datos ficticios.

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

La aplicación queda disponible en `http://localhost:5173`. Rutas: `/web`, `/whatsapp`, `/callcenter`, `/app`, `/admin`, `/mailbox` y `/login`.

## Pruebas

```powershell
cd backend
pytest
```

## Credenciales ficticias

- Asesor: `asesor` / `Asesor#2026`
- Admin: `admin` / `Admin#2026`
- Paciente: correo ficticio + OTP (se implementará en una rebanada posterior)

