from collections import Counter, defaultdict

from ..cases import derive_status, empty_steps
from ..events.safe import CHANNELS


FUNNEL = ("cotizando", "datos_completos", "clinica_elegida", "horario_propuesto", "cita_confirmada")
STATUSES = (*FUNNEL, "cancelado")
STEP_EVENTS = {
    "estudio_seleccionado": "study",
    "datos_paciente_capturados": "patient_data",
    "clinica_seleccionada": "clinic",
    "horario_propuesto": "slot",
    "cita_confirmada": "confirmed",
}


def _journey(events, fallback):
    route = []

    def visit(channel):
        if isinstance(channel, str) and channel in CHANNELS and (not route or route[-1] != channel):
            route.append(channel)

    for event in events:
        if event.type == "acceso_denegado":
            continue
        if event.type == "canal_cambiado":
            payload = event.payload or {}
            if not route:
                visit(payload.get("from"))
            visit(payload.get("to"))
        visit(event.channel)
    if not route:
        visit(fallback)
    return route


def _recovered(events, route):
    if len(set(route)) < 2:
        return False
    steps = empty_steps()
    switched = False
    for event in events:
        if event.type == "canal_cambiado":
            payload = event.payload or {}
            origin, target = payload.get("from"), payload.get("to")
            if isinstance(origin, str) and isinstance(target, str) and origin in CHANNELS and target in CHANNELS:
                switched |= origin != target
        if event.type == "tramite_cancelado":
            break
        step = STEP_EVENTS.get(event.type)
        if step:
            before = derive_status(steps)
            steps[step] = True
            if switched and FUNNEL.index(derive_status(steps)) > FUNNEL.index(before):
                return True
    return False


def journeys(cases, events):
    by_case = defaultdict(list)
    for event in events:
        if event.case_id:
            by_case[event.case_id].append(event)
    return {
        case.id: _journey(by_case[case.id], case.last_channel)
        for case in cases
    }, by_case


def dashboard_counts(cases, route_by_case, by_case):
    totals = Counter(case.status for case in cases)
    durations = []
    for case in cases:
        trace = by_case[case.id]
        created = next((event for event in trace if event.type == "tramite_creado"), None)
        confirmed = next((event for event in trace if event.type == "cita_confirmada"), None)
        if created and confirmed and confirmed.timestamp >= created.timestamp:
            durations.append((confirmed.timestamp - created.timestamp).total_seconds())
    return {
        "total_cases": len(cases),
        "totals_by_status": {status: totals[status] for status in STATUSES},
        "abandoned": sum(case.abandoned for case in cases),
        "recovered_across_channels": sum(_recovered(by_case[case.id], route_by_case[case.id]) for case in cases),
        "average_confirmation_seconds": round(sum(durations) / len(durations)) if durations else None,
        "funnel": [{"status": status, "count": totals[status]} for status in FUNNEL],
    }
