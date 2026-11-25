# Demo del centro de contacto

1. En Web, registra a Ana con el teléfono +522220000001 y el correo ana.demo@example.com. Elige el estudio y la clínica.
2. En WhatsApp, retoma el trámite de Ana y elige un horario.
3. En Llamada, ingresa el número de Ana y pulsa Llamada entrante. Deja el campo vacío para simular un número oculto.
4. En Identificar, busca por teléfono o correo y selecciona a la persona reconocida.
5. En Verificar identidad, escribe la fecha de nacimiento que registró Ana.
6. En Atender, revisa el horario y la línea de tiempo, agrega una nota interna y confirma la cita.
7. Pulsa Terminar llamada y comprueba que el contexto deja de estar disponible.

## Tablero y auditoría

- Tras el reset, abre `/admin` y filtra la bitácora por **Verificación fallida**, **Acceso denegado** o **Contexto consultado**.
- El historial ficticio de C-1005 incluye un bloqueo temporal pasado. C-1007, C-1008 y C-1009 incluyen llamadas y consultas del asesor. El feed inicial contiene mensajes, cambios de canal y una cita confirmada.
- Ana empieza sin persona, trámite ni historial. Al completar el recorrido anterior, sus nuevos eventos llegan al feed por SSE.
