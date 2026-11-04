"""Búsqueda y programación: nunca confirma presencia física."""

from datetime import timedelta

from sqlalchemy import or_, select

from app.models import Asignatura, Aula, BloqueHorario, Docente, Grupo, Horario, Incidencia
from app.services import calendario
from app.services.comun import ErrorNegocio, NoEncontrado, normalizar
from asi_shared import turno_de


def horarios_en_fecha(sesion, fecha):
    return list(
        sesion.scalars(
            select(Horario).where(
                Horario.estado.in_(["vigente", "historico"]),
                Horario.vigencia_confirmada.is_(True),
                Horario.vigente_desde <= fecha,
                or_(Horario.vigente_hasta.is_(None), Horario.vigente_hasta >= fecha),
            )
        )
    )


def bloques_en_fecha(sesion, fecha):
    for h in horarios_en_fecha(sesion, fecha):
        if not h.periodo.fecha_inicio <= fecha <= h.periodo.fecha_fin:
            continue
        for b in h.bloques:
            if b.dia == fecha.weekday():
                yield h, b


def coincide_grupo(grupo, carrera=None, semestre=None, letra=None, periodo_id=None):
    return bool(
        grupo
        and not grupo.pendiente_validacion
        and (not carrera or normalizar(grupo.carrera) == normalizar(carrera))
        and (semestre is None or grupo.semestre == semestre)
        and (not letra or normalizar(grupo.letra) == normalizar(letra))
        and (periodo_id is None or grupo.periodo_id == periodo_id)
    )


def fila(h, b, fecha):
    return {
        "bloque_id": b.id,
        "horario_id": h.id,
        "version": h.version,
        "fecha": fecha,
        "dia": b.dia,
        "inicio": b.hora_inicio,
        "fin": b.hora_fin,
        "docente_id": h.docente_id,
        "docente": h.docente.nombre,
        "asignatura_id": b.asignatura_id,
        "materia": b.asignatura.nombre,
        "grupo_id": b.grupo_id,
        "grupo": b.grupo.clave if b.grupo else None,
        "grupo_pendiente": b.grupo_letra if b.grupo_id is None else None,
        "aula_id": b.aula_id,
        "aula": b.aula.clave if b.aula else None,
        "turno": turno_de(b.hora_inicio).value,
    }


def buscar(
    sesion,
    permisos,
    texto="",
    fecha=None,
    carrera=None,
    semestre=None,
    periodo_id=None,
    dia=None,
    turno=None,
    limite=100,
    offset=0,
):
    q = normalizar(texto)
    filtros_horario = any(v is not None for v in (carrera, semestre, periodo_id, dia, turno))
    actividades = []
    docentes_ids, materias_ids, grupos_ids, aulas_ids = set(), set(), set(), set()
    if "horarios.ver" in permisos:
        for h in horarios_en_fecha(sesion, fecha):
            if not h.periodo.fecha_inicio <= fecha <= h.periodo.fecha_fin:
                continue
            if periodo_id is not None and h.periodo_id != periodo_id:
                continue
            for b in h.bloques:
                if dia is not None and b.dia != dia:
                    continue
                if turno and turno_de(b.hora_inicio) != turno:
                    continue
                if (carrera or semestre is not None) and not coincide_grupo(
                    b.grupo, carrera, semestre
                ):
                    continue
                docentes_ids.add(h.docente_id)
                materias_ids.add(b.asignatura_id)
                grupos_ids.add(b.grupo_id)
                aulas_ids.add(b.aula_id)
                f = fila(h, b, fecha)
                if not q or q in normalizar(
                    " ".join(str(f[k] or "") for k in ("docente", "materia", "grupo", "aula"))
                ):
                    actividades.append(f)
    salida = {}
    for clave, modelo, campo, permiso, ids in (
        ("docentes", Docente, "nombre", "docentes.ver", docentes_ids),
        ("materias", Asignatura, "nombre", "horarios.ver", materias_ids),
        ("grupos", Grupo, "clave", "horarios.ver", grupos_ids),
        ("aulas", Aula, "clave", "horarios.ver", aulas_ids),
    ):
        registros = []
        if permiso in permisos:
            for obj in sesion.scalars(select(modelo).order_by(modelo.id)):
                nombre = getattr(obj, campo)
                if q and q not in normalizar(nombre):
                    continue
                if filtros_horario and obj.id not in ids:
                    continue
                registros.append({"id": obj.id, "nombre": nombre, "activo": obj.activo})
        salida[clave] = {"total": len(registros), "resultados": registros[offset : offset + limite]}
    salida["actividades"] = {
        "total": len(actividades),
        "resultados": actividades[offset : offset + limite],
    }
    salida["fecha_vigencia"] = fecha
    salida["aviso"] = "Actividades de versiones con vigencia confirmada para la fecha consultada."
    return salida


def grupo_semanal(sesion, grupo_id, fecha):
    grupo = sesion.get(Grupo, grupo_id)
    if grupo is None:
        raise NoEncontrado("El grupo")
    if grupo.pendiente_validacion:
        raise ErrorNegocio("El grupo requiere carrera, semestre y periodo confirmados", 409)
    lunes = fecha - timedelta(days=fecha.weekday())
    filas = []
    for i in range(7):
        dia = lunes + timedelta(days=i)
        for h, b in bloques_en_fecha(sesion, dia):
            if b.grupo_id != grupo_id or h.periodo_id != grupo.periodo_id:
                continue
            estado = calendario.estado_dia(sesion, dia, turno_de(b.hora_inicio).value)
            filas.append(
                {
                    **fila(h, b, dia),
                    "habil": estado.habil,
                    "aviso_calendario": estado.motivo,
                    "conflictos": [],
                }
            )
    for i, a in enumerate(filas):
        for b in filas[i + 1 :]:
            if a["fecha"] == b["fecha"] and a["inicio"] < b["fin"] and b["inicio"] < a["fin"]:
                a["conflictos"].append(b["bloque_id"])
                b["conflictos"].append(a["bloque_id"])
    filas.sort(key=lambda f: (f["fecha"], f["inicio"], f["docente"]))
    desconocidos = list(
        sesion.scalars(
            select(Horario.id)
            .join(BloqueHorario)
            .where(
                BloqueHorario.grupo_id == grupo_id,
                Horario.periodo_id == grupo.periodo_id,
                Horario.estado.in_(["vigente", "historico"]),
                Horario.vigencia_confirmada.is_(False),
            )
            .distinct()
        )
    )
    return {
        "grupo_id": grupo.id,
        "grupo": grupo.clave,
        "periodo_id": grupo.periodo_id,
        "desde": lunes,
        "hasta": lunes + timedelta(days=6),
        "bloques": filas,
        "horarios_sin_vigencia_confirmada": desconocidos,
        "aviso": "Horario programado. La presencia física no está confirmada. "
        "Las versiones de vigencia desconocida se excluyen.",
    }


def ubicacion(sesion, docente_id, fecha, hora):
    docente = sesion.get(Docente, docente_id)
    if docente is None:
        raise NoEncontrado("El docente")
    # Los periodos de los desconocidos se revisan explícitamente.
    desconocidos = [
        h
        for h in sesion.scalars(
            select(Horario).where(
                Horario.docente_id == docente_id,
                Horario.estado.in_(["vigente", "historico"]),
                Horario.vigencia_confirmada.is_(False),
            )
        )
        if h.periodo.fecha_inicio <= fecha <= h.periodo.fecha_fin
    ]
    activos = [
        (h, b)
        for h, b in bloques_en_fecha(sesion, fecha)
        if h.docente_id == docente_id and b.hora_inicio <= hora < b.hora_fin
    ]
    turno = turno_de(hora).value
    incidentes = list(
        sesion.scalars(
            select(Incidencia)
            .where(
                Incidencia.fecha == fecha,
                Incidencia.anulada.is_(False),
                or_(Incidencia.docente_id.is_(None), Incidencia.docente_id == docente_id),
            )
            .order_by(Incidencia.id)
        )
    )
    resultados = []
    for h, b in activos:
        aplican = [i for i in incidentes if i.turno in (None, turno_de(b.hora_inicio).value)]
        habil = calendario.estado_dia(sesion, fecha, turno_de(b.hora_inicio).value)
        estado = (
            "suspendida"
            if not habil.habil
            else "requiere_verificacion"
            if aplican
            else "programada"
        )
        resultados.append(
            {
                **fila(h, b, fecha),
                "estado": estado,
                "aula_programada": b.aula.clave if b.aula and habil.habil and not aplican else None,
                "aviso_calendario": habil.motivo,
                "incidencias": [
                    {"id": i.id, "tipo": i.tipo, "descripcion": i.descripcion} for i in aplican
                ],
            }
        )
    return {
        "docente_id": docente.id,
        "docente": docente.nombre,
        "fecha": fecha,
        "hora": hora,
        "tipo": "ubicacion_programada",
        "ubicacion_real": None,
        "estado": (
            "con_programacion"
            if resultados
            else "vigencia_desconocida"
            if desconocidos
            else "sin_clase_asignada"
        ),
        "bloques": resultados,
        "conflicto": len(resultados) > 1,
        "horarios_sin_vigencia_confirmada": [h.id for h in desconocidos],
        "incidencias": [
            {"id": i.id, "tipo": i.tipo, "descripcion": i.descripcion}
            for i in incidentes
            if i.turno in (None, turno)
        ],
        "aviso": "Ubicación programada; no confirma presencia física. Las incidencias "
        "de texto libre requieren revisión; no se deduce un aula de su descripción.",
    }
