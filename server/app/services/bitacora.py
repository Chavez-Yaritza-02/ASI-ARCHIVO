"""Bitácora diaria: lo programado (horarios vigentes en la fecha) frente a lo registrado.

- La lista de docentes esperados se calcula, no se guarda. Usa la versión de horario
  que regía en esa fecha (vigente_desde / vigente_hasta), no la actual.
- Unidad de registro: docente + fecha + turno (matutino antes de las 14:00).
- Sin registro = "pendiente". En días inhábiles = "inhabil". Nunca se generan faltas.
- Corregir un registro exige motivo; corregir días anteriores, el permiso
  asistencia.corregir. Todo queda en la auditoría (historial consultable).
"""

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import (
    Asistencia,
    Auditoria,
    BloqueHorario,
    Docente,
    Horario,
    Incidencia,
    Periodo,
    Usuario,
)
from app.services import calendario
from app.services.comun import ErrorNegocio, NoEncontrado, auditar, hoy, instantanea
from asi_shared import Permiso, turno_de

ESTADOS = ("pendiente", "inhabil", "asistio", "retardo", "falto", "justificado")
CAMPOS = ["estado", "hora_entrada", "hora_salida", "observaciones", "justificacion"]
DIAS_MAXIMOS_RANGO = 93
TOLERANCIA_RETARDO = timedelta(minutes=10)


@dataclass
class Programacion:
    docente: Docente
    turno: str
    horario_id: int
    bloques: list[BloqueHorario] = field(default_factory=list)

    @property
    def inicio(self) -> time:
        return min(b.hora_inicio for b in self.bloques)

    @property
    def fin(self) -> time:
        return max(b.hora_fin for b in self.bloques)


def periodo_de(sesion: Session, fecha: date) -> Periodo | None:
    return sesion.scalar(
        select(Periodo).where(
            Periodo.fecha_inicio <= fecha,
            Periodo.fecha_fin >= fecha,
            Periodo.estado != "borrador",
        )
    )


def programacion(sesion: Session, fecha: date) -> dict[tuple[int, str], Programacion]:
    """Docentes y actividades programadas en la fecha, agrupados por (docente, turno)."""
    periodo = periodo_de(sesion, fecha)
    if periodo is None or fecha.weekday() > 5:
        return {}
    horarios = sesion.scalars(
        select(Horario).where(
            Horario.periodo_id == periodo.id,
            Horario.estado.in_(("vigente", "historico")),
            Horario.vigente_desde <= fecha,
            or_(Horario.vigente_hasta.is_(None), Horario.vigente_hasta >= fecha),
        )
    ).all()
    resultado: dict[tuple[int, str], Programacion] = {}
    for h in horarios:
        for b in h.bloques:
            if b.dia != fecha.weekday():
                continue
            turno = turno_de(b.hora_inicio).value
            clave = (h.docente_id, turno)
            resultado.setdefault(clave, Programacion(h.docente, turno, h.id)).bloques.append(b)
    return resultado


def _minutos_retardo(inicio: time | None, entrada: time | None) -> int | None:
    if inicio is None or entrada is None:
        return None
    diferencia = datetime.combine(date.min, entrada) - datetime.combine(date.min, inicio)
    minutos = int(diferencia.total_seconds() // 60)
    return minutos if minutos > 0 else 0


def _actividad(b: BloqueHorario) -> dict:
    return {
        "asignatura": b.asignatura.nombre,
        "grupo": b.grupo.clave if b.grupo else (f"{b.grupo_letra}?" if b.grupo_letra else None),
        "aula": b.aula.clave if b.aula else None,
        "inicio": b.hora_inicio,
        "fin": b.hora_fin,
    }


def dia(
    sesion: Session,
    fecha: date,
    turno: str | None = None,
    docente_id: int | None = None,
    estado: str | None = None,
) -> dict:
    """Bitácora de un día: filas (programado + registro), resumen e incidencias."""
    periodo = periodo_de(sesion, fecha)
    del_dia = calendario.estado_dia(sesion, fecha)
    programado = programacion(sesion, fecha)
    registros = {
        (a.docente_id, a.turno): a
        for a in sesion.scalars(select(Asistencia).where(Asistencia.fecha == fecha))
    }
    filas = []
    for clave in sorted(
        set(programado) | set(registros),
        key=lambda k: (k[1] != "matutino", _nombre(programado, registros, k)),
    ):
        p, a = programado.get(clave), registros.get(clave)
        if (turno and clave[1] != turno) or (docente_id and clave[0] != docente_id):
            continue
        estado_turno = calendario.estado_dia(sesion, fecha, clave[1])
        inicio = p.inicio if p else a.programado_inicio
        fin = p.fin if p else a.programado_fin
        if a is not None:
            situacion = a.estado
        elif not estado_turno.habil:
            situacion = "inhabil"
        else:
            situacion = "pendiente"
        filas.append(
            {
                "docente": {"id": clave[0], "nombre": (p.docente if p else a.docente).nombre},
                "turno": clave[1],
                "programado_inicio": inicio,
                "programado_fin": fin,
                "actividades": [
                    _actividad(b) for b in sorted(p.bloques, key=lambda b: b.hora_inicio)
                ]
                if p
                else [],
                "horario_id": p.horario_id if p else a.horario_id,
                "estado": situacion,
                "dia_habil": estado_turno.habil,
                "motivo_inhabil": "" if estado_turno.habil else estado_turno.motivo,
                "fuera_de_programacion": p is None,
                "asistencia": _registro(a) if a else None,
                "minutos_retardo": _minutos_retardo(inicio, a.hora_entrada) if a else None,
                "tolerancia_minutos": int(TOLERANCIA_RETARDO.total_seconds() // 60),
            }
        )
    resumen = {e: 0 for e in ESTADOS}
    for f in filas:
        resumen[f["estado"]] += 1
    if estado:
        filas = [f for f in filas if f["estado"] == estado]
    incidencias = sesion.scalars(
        select(Incidencia)
        .where(Incidencia.fecha == fecha, Incidencia.anulada.is_(False))
        .order_by(Incidencia.id)
    ).all()
    return {
        "fecha": fecha,
        "periodo": {"id": periodo.id, "nombre": periodo.nombre, "estado": periodo.estado}
        if periodo
        else None,
        "dia_habil": del_dia.habil,
        "motivo": del_dia.motivo,
        "filas": filas,
        "resumen": resumen,
        "incidencias": [
            i
            for i in incidencias
            if (not docente_id or i.docente_id == docente_id)
            and (not turno or i.turno in (None, turno))
        ],
    }


def _nombre(programado, registros, clave) -> str:
    p = programado.get(clave)
    return (p.docente if p else registros[clave].docente).nombre


def _registro(a: Asistencia) -> dict:
    return {
        "id": a.id,
        "estado": a.estado,
        "hora_entrada": a.hora_entrada,
        "hora_salida": a.hora_salida,
        "observaciones": a.observaciones,
        "justificacion": a.justificacion,
        "en_dia_inhabil": a.en_dia_inhabil,
        "correcciones": a.correcciones,
        "actualizado_en": a.actualizado_en,
    }


def rango(
    sesion: Session,
    desde: date,
    hasta: date,
    docente_id: int | None = None,
    turno: str | None = None,
) -> list[dict]:
    """Bitácoras de varios días (para reportes)."""
    if hasta < desde:
        raise ErrorNegocio("La fecha final no puede ser anterior a la inicial", 422)
    if (hasta - desde).days >= DIAS_MAXIMOS_RANGO:
        raise ErrorNegocio(f"El rango máximo es de {DIAS_MAXIMOS_RANGO} días", 422)
    dias = []
    actual = desde
    while actual <= hasta:
        dias.append(dia(sesion, actual, turno, docente_id))
        actual += timedelta(days=1)
    return dias


# --- Registro y corrección ------------------------------------------------------------


def _validar_campos(datos: dict) -> None:
    estado = datos["estado"]
    if estado not in ("asistio", "retardo", "falto", "justificado"):
        raise ErrorNegocio(f"Estado inválido: {estado}", 422)
    entrada, salida = datos.get("hora_entrada"), datos.get("hora_salida")
    if estado == "falto" and (entrada or salida):
        raise ErrorNegocio("Una falta no lleva hora de entrada ni de salida", 422)
    if estado == "retardo" and entrada is None:
        raise ErrorNegocio("Indica la hora real de entrada del retardo", 422)
    if estado == "justificado" and not (datos.get("justificacion") or "").strip():
        raise ErrorNegocio("Escribe la justificación (motivo o documento)", 422)
    if entrada and salida and salida <= entrada:
        raise ErrorNegocio("La hora de salida debe ser posterior a la de entrada", 422)


def _exigir_periodo_abierto(sesion: Session, fecha: date) -> Periodo:
    periodo = periodo_de(sesion, fecha)
    if periodo is None:
        raise ErrorNegocio(f"El {fecha:%d/%m/%Y} no pertenece a ningún periodo activo", 409)
    if periodo.estado == "cerrado":
        raise ErrorNegocio(f"El periodo {periodo.nombre} está cerrado", 409)
    return periodo


def registrar(
    sesion: Session,
    usuario: Usuario,
    docente_id: int,
    fecha: date,
    turno: str,
    datos: dict,
    autorizar_dia_inhabil: bool = False,
) -> Asistencia:
    _exigir_periodo_abierto(sesion, fecha)
    if fecha > hoy() and datos["estado"] != "justificado":
        raise ErrorNegocio("Solo se registran justificaciones en fechas futuras", 422)
    p = programacion(sesion, fecha).get((docente_id, turno))
    if p is None:
        raise ErrorNegocio(
            f"El docente no tiene actividades programadas el {fecha:%d/%m/%Y} en el turno "
            f"{turno}. Si es un caso especial, registra una incidencia.",
            422,
        )
    estado_turno = calendario.estado_dia(sesion, fecha, turno)
    if not estado_turno.habil:
        if not autorizar_dia_inhabil:
            raise ErrorNegocio(f"{estado_turno.motivo}: no se registra asistencia", 409)
        if Permiso.ASISTENCIA_CORREGIR not in usuario.permisos:
            raise ErrorNegocio("Registrar en día inhábil requiere autorización", 403)
    existente = sesion.scalar(
        select(Asistencia).where(
            Asistencia.docente_id == docente_id,
            Asistencia.fecha == fecha,
            Asistencia.turno == turno,
        )
    )
    if existente is not None:
        raise ErrorNegocio(
            "Ya hay un registro para este docente, fecha y turno; corrígelo",
            409,
            [f"Registro {existente.id}: {existente.estado}"],
        )
    _validar_campos(datos)
    asistencia = Asistencia(
        docente_id=docente_id,
        fecha=fecha,
        turno=turno,
        estado=datos["estado"],
        hora_entrada=datos.get("hora_entrada"),
        hora_salida=datos.get("hora_salida"),
        observaciones=(datos.get("observaciones") or "").strip(),
        justificacion=(datos.get("justificacion") or "").strip(),
        horario_id=p.horario_id,
        programado_inicio=p.inicio,
        programado_fin=p.fin,
        en_dia_inhabil=not estado_turno.habil,
        registrado_por_id=usuario.id,
    )
    sesion.add(asistencia)
    sesion.flush()
    auditar(
        sesion,
        usuario,
        "registrar",
        "asistencia",
        asistencia.id,
        despues={
            **instantanea(asistencia, CAMPOS),
            "docente_id": docente_id,
            "fecha": fecha,
            "turno": turno,
            "en_dia_inhabil": asistencia.en_dia_inhabil,
        },
    )
    sesion.commit()
    return asistencia


def obtener(sesion: Session, id_: int) -> Asistencia:
    asistencia = sesion.get(Asistencia, id_)
    if asistencia is None:
        raise NoEncontrado("El registro de asistencia")
    return asistencia


def corregir(sesion: Session, usuario: Usuario, id_: int, cambios: dict, motivo: str) -> Asistencia:
    """Corrige un registro. Siempre exige motivo; días anteriores, permiso de corrección."""
    asistencia = obtener(sesion, id_)
    _exigir_periodo_abierto(sesion, asistencia.fecha)
    if len((motivo or "").strip()) < 5:
        raise ErrorNegocio("Escribe el motivo de la corrección", 422)
    if asistencia.fecha < hoy() and Permiso.ASISTENCIA_CORREGIR not in usuario.permisos:
        raise ErrorNegocio("Corregir días anteriores requiere autorización", 403)
    antes = instantanea(asistencia, CAMPOS)
    datos = {**{c: getattr(asistencia, c) for c in CAMPOS}, **cambios}
    if datos["estado"] == "falto":
        datos["hora_entrada"] = datos["hora_salida"] = None
    _validar_campos(datos)
    for clave in CAMPOS:
        valor = datos[clave]
        setattr(asistencia, clave, valor.strip() if isinstance(valor, str) else valor)
    despues = instantanea(asistencia, CAMPOS)
    if despues == antes:
        raise ErrorNegocio("No hay cambios que corregir", 422)
    asistencia.correcciones += 1
    auditar(
        sesion,
        usuario,
        "corregir",
        "asistencia",
        asistencia.id,
        antes=antes,
        despues={**despues, "motivo": motivo.strip()},
    )
    sesion.commit()
    return asistencia


def historial(sesion: Session, id_: int) -> list[dict]:
    obtener(sesion, id_)
    registros = sesion.scalars(
        select(Auditoria)
        .where(Auditoria.entidad == "asistencia", Auditoria.entidad_id == str(id_))
        .order_by(Auditoria.id)
    ).all()
    usuarios = {u.id: u.nombre for u in sesion.scalars(select(Usuario))}
    return [
        {
            "fecha": r.fecha,
            "usuario": usuarios.get(r.usuario_id, "—"),
            "accion": r.accion,
            "antes": r.antes,
            "despues": r.despues,
        }
        for r in registros
    ]


# --- Incidencias --------------------------------------------------------------------------

CAMPOS_INCIDENCIA = ["fecha", "docente_id", "turno", "tipo", "descripcion", "anulada"]


def crear_incidencia(sesion: Session, usuario: Usuario, datos: dict) -> Incidencia:
    if not (datos.get("descripcion") or "").strip():
        raise ErrorNegocio("Describe la incidencia", 422)
    _exigir_periodo_abierto(sesion, datos["fecha"])
    if datos.get("docente_id") and sesion.get(Docente, datos["docente_id"]) is None:
        raise NoEncontrado("El docente")
    incidencia = Incidencia(**datos, registrado_por_id=usuario.id)
    incidencia.descripcion = incidencia.descripcion.strip()
    sesion.add(incidencia)
    sesion.flush()
    auditar(
        sesion,
        usuario,
        "crear",
        "incidencia",
        incidencia.id,
        despues=instantanea(incidencia, CAMPOS_INCIDENCIA),
    )
    sesion.commit()
    return incidencia


def editar_incidencia(sesion: Session, usuario: Usuario, id_: int, cambios: dict) -> Incidencia:
    incidencia = sesion.get(Incidencia, id_)
    if incidencia is None:
        raise NoEncontrado("La incidencia")
    if incidencia.anulada:
        raise ErrorNegocio("La incidencia está anulada", 409)
    _exigir_periodo_abierto(sesion, incidencia.fecha)
    antes = instantanea(incidencia, CAMPOS_INCIDENCIA)
    for clave, valor in cambios.items():
        setattr(incidencia, clave, valor.strip() if isinstance(valor, str) else valor)
    if not incidencia.descripcion:
        raise ErrorNegocio("Describe la incidencia", 422)
    accion = "anular" if incidencia.anulada else "editar"
    auditar(
        sesion,
        usuario,
        accion,
        "incidencia",
        incidencia.id,
        antes,
        instantanea(incidencia, CAMPOS_INCIDENCIA),
    )
    sesion.commit()
    return incidencia


def listar_incidencias(
    sesion: Session, desde: date, hasta: date, docente_id: int | None = None
) -> list[Incidencia]:
    consulta = (
        select(Incidencia)
        .where(Incidencia.fecha >= desde, Incidencia.fecha <= hasta, Incidencia.anulada.is_(False))
        .order_by(Incidencia.fecha, Incidencia.id)
    )
    if docente_id:
        consulta = consulta.where(Incidencia.docente_id == docente_id)
    return list(sesion.scalars(consulta))
