# Guion final de la demo · 6:30

Límite de 7:00. Reserva los últimos 30 segundos para un imprevisto. Ana inicia un solo trámite de **Ultrasonido abdominal**. Web captura los datos, WhatsApp elige la clínica, App elige el horario y Call Center confirma. Admin observa el recorrido.

## Checklist previo

- [ ] Con `DEMO_MODE=true`, ejecuta `python -m app.modules.demo.reset` desde `backend`. Ya incluye el seed. Verifica que aparezcan C-1001 y C-1002 y que Ana aún no exista. Haz el reset antes de iniciar sesiones.
- [ ] Arranca el backend con `python -m app.dev` desde `backend` y el frontend con `npm run dev` desde `frontend`. Las rutas del guion usan `http://localhost:5173`.
- [ ] Abre Web, WhatsApp, [buzón de Ana](http://localhost:5173/mailbox?email=ana.demo%40example.com) y App en pestañas. Deja Web al frente. En WhatsApp, prepara **Otro número** con el teléfono de Ana sin enviar todavía «hola».
- [ ] Inicia sesión en dos ventanas separadas desde `/login`. En la de asesor usa `asesor` / `Asesor#2026` y deja `/callcenter` sin llamada activa. En la de admin usa `admin` / `Admin#2026` y comprueba que `/admin` diga **Conectado**. Mantén Admin visible junto a Call Center cuando se confirme la cita para mostrar el evento en vivo.
- [ ] Abre el [archivo de apoyo](docs/DEMO_PARA_PEGAR.md) para pegar los datos. Ten el cronómetro listo. Ana se crea durante la demo, por lo que su primer acceso a App requiere autenticación después del alta.

## 0:00–0:25 · Apertura

- **URL** · `/web`. Sin credenciales. Deja el cursor quieto y la pantalla inicial visible.
- **En pantalla** · «Cotiza y agenda tu estudio» y **Comenzar cotización**.
- **Narración** · «Vamos a seguir un solo trámite de Ana. Cada canal continúa desde lo que el anterior ya resolvió».

## 0:25–1:25 · Web

- **URL y datos** · `/web`. Ana Demo · 10/05/1990 · `ana.demo@example.com` · `+522220000001`.
- **Acción** · **Comenzar cotización** → **Ultrasonido abdominal** → **Cotizar este estudio**. Escribe los cuatro datos y deja **Para mí**. Sal del último campo y espera **Guardado**. Pulsa F5 en la misma pestaña. Tras comprobar que vuelve el formulario lleno, pulsa **Guardar y continuar**. Detente antes de elegir clínica.
- **En pantalla** · Precio ficticio de **$420 MXN**, borrador recuperado y luego **Elige una clínica**.
- **Narración** · «Ana captura sus datos una vez. Incluso al recargar, Web recupera el borrador de esta sesión».

## 1:25–2:30 · WhatsApp

- **URL y datos** · `/whatsapp`, número `+522220000001`, fecha `10/05/1990`. Buzón `/mailbox?email=ana.demo%40example.com`.
- **Acción** · Envía «hola» desde **Otro número**, escribe la fecha y consulta el buzón. Pega el OTP más reciente en el chat. Pulsa **Continuar** y **Clínica Puebla Centro (demo)**. Cambia a App sin elegir horario.
- **En pantalla** · El saludo actual dice «Hola Ana Demo» y avisa que hay un trámite pendiente. El estudio, la clínica y el horario quedan reservados hasta verificar. El OTP llega al buzón.
- **Narración** · «El teléfono permite reconocer a Ana. La fecha y el código del buzón habilitan la retoma y aquí solo elegimos la clínica».

## 2:30–3:20 · App

- **URL y datos** · `/app`, `ana.demo@example.com`.
- **Acción** · Si la sesión está vigente, entra directo a **Mis trámites**. En el primer acceso tras el reset, pega el correo, pulsa **Enviar código**, consulta el nuevo mensaje en el buzón y pulsa **Verificar código**. Abre el folio de Ana, muestra **Línea de tiempo** y elige el primer horario disponible de **09:00**. Deja pendiente **Confirmar cita**.
- **En pantalla** · Mismo estudio y clínica, línea de tiempo con Web, WhatsApp y App, y horario local de Ciudad de México.
- **Narración** · «La App recupera el folio y su historial. Ana agrega la hora sin volver a capturar sus datos».

## 3:20–4:30 · Call Center

- **URL y datos** · `/callcenter`, `asesor` / `Asesor#2026`, teléfono `+522220000001`, fecha `10/05/1990`.
- **Acción** · Pega el número y pulsa **Llamada entrante**. En **Identificar**, usa la coincidencia que carga la llamada o búscala por teléfono si hace falta. Pulsa **Seleccionar esta persona**, escribe la fecha y pulsa **Verificar**. En **Atender**, muestra la línea de tiempo y pulsa **Confirmar cita**.
- **En pantalla** · **Reconocida · sin verificar** y nombre enmascarado al inicio. Después de verificar, el asesor ve el mismo estudio, clínica y horario de App. El estado cambia a **Cita confirmada**.
- **Narración** · «El asesor verifica a la solicitante para abrir el contexto. Tiene la hora elegida en App y solo confirma la cita».

## 4:30–6:00 · Admin

- **URL y credenciales** · `/admin`, `admin` / `Admin#2026`. Usa el folio anotado en App o Call Center.
- **Acción** · Localiza el folio en **Trámites** y señala su **Recorrido**. Baja a **Eventos en vivo** y muestra la confirmación. En **Bitácora de auditoría**, filtra por **Contexto consultado** y ubica la entrada reciente del asesor.
- **En pantalla** · **Cita confirmada**, recorrido **Web → WhatsApp → App → Call Center**, contacto enmascarado como `A*** D.`, `***0001` y `a***@example.com`, y evento de confirmación. La fila muestra el recorrido y el feed muestra los eventos recientes. La línea de tiempo detallada del folio se muestra en Call Center.
- **Narración** · «El tablero muestra por dónde pasó el trámite y quién consultó el contexto. El administrador ve datos enmascarados».

## 6:00–6:30 · Cierre

- **URL y datos** · `/admin`, misma sesión y folio de Ana.
- **Acción** · Deja visible la fila con **Cita confirmada** y los cuatro canales. Termina sin hacer otra operación.
- **En pantalla** · Un mismo folio desde la cotización hasta la confirmación.
- **Narración** · «Un ultrasonido, un folio y cuatro canales de atención. Cada uno añadió un paso al mismo trámite».

## Respaldo para preguntas

Haz estas escenas después del cierre. En Call Center, pulsa **Terminar llamada** antes de iniciar cada ejemplo con otro número.

| Escena | Pasos | Resultado esperado |
|---|---|---|
| Teléfono compartido | En `/whatsapp`, selecciona **Marta / Pablo** (`+522229999999`) y envía «hola». Si quieres seguir, escribe `20/08/1982` para Marta o `15/03/2012` para Pablo. | Pide fecha para desambiguar antes de mostrar datos del trámite. El OTP se busca en el buzón del correo correspondiente. |
| Número desconocido | En `/whatsapp`, elige **Otro número**, usa `+522220000099` recién reiniciada la demo y envía «hola». | Aparecen el saludo y las opciones de cotizar o agendar. |
| Bloqueo tras tres intentos | En `/callcenter`, abre una llamada para Luis (`+522221111111`), selecciona el resultado e introduce `01/01/2000` tres veces. | Baja el contador y el tercer fallo muestra el bloqueo y el tiempo restante. Con `LOCKOUT_MINUTES=2` dura dos minutos. |
| Trámite para tercero | En `/app`, entra como `marta.demo@example.com` con el OTP del buzón. Abre **C-1002**. | El resumen distingue a Pablo Demo como paciente y muestra el parentesco **Hijo o hija**. |
| Llamada con número oculto | En `/callcenter`, termina cualquier llamada previa, deja **Número entrante** vacío y pulsa **Llamada entrante**. Busca a Marta por `marta.demo@example.com`, selecciónala y verifica con `20/08/1982`. | Aparece **Número oculto**. El contexto para Marta y Pablo se habilita tras la verificación asistida. |
