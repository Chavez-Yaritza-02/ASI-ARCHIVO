"""Asistencia independiente por tramo <=60 min; sin inferir asistencias ni faltas."""

from datetime import date, datetime, timedelta

from sqlalchemy import select

from app.models import Asistencia, AsistenciaHora, Auditoria, Docente, Horario, Periodo, Usuario
from app.services import bitacora, calendario, configuracion, consultas
from app.services.comun import ErrorNegocio, NoEncontrado, auditar, hoy, instantanea
from asi_shared import Permiso, turno_de

CAMPOS = [
    "estado",
    "hora_entrada",
    "hora_salida",
    "minutos_cumplidos",
    "minutos_justificados",
    "observaciones",
    "justificacion",
]
COPIA = [
    "docente_id",
    "docente_nombre",
    "fecha",
    "periodo_id",
    "horario_id",
    "bloque_id",
    "asignatura",
    "tipo_actividad",
    "grupo",
    "aula",
    "turno",
    "programado_inicio",
    "programado_fin",
    "en_dia_inhabil",
]
METRICAS = (
    "programadas",
    "exigibles",
    "cumplidas",
    "faltantes",
    "justificadas",
    "pendientes",
    "suspendidas",
)


def minutos(inicio, fin):
    return int(
        (datetime.combine(date.min, fin) - datetime.combine(date.min, inicio)).total_seconds() // 60
    )


def _precision(hora):
    return hora.tzinfo is None and hora.second == 0 and hora.microsecond == 0


def programacion(sesion, fecha):
    filas = []
    for h, b in consultas.bloques_en_fecha(sesion, fecha):
        if h.periodo.estado == "borrador":
            continue
        if not _precision(b.hora_inicio) or not _precision(b.hora_fin):
            raise ErrorNegocio(
                "El horario contiene segundos: revisa sus horas antes de capturar", 422
            )
        inicio = datetime.combine(fecha, b.hora_inicio)
        fin = datetime.combine(fecha, b.hora_fin)
        while inicio < fin:
            siguiente = min(inicio + timedelta(minutes=60), fin)
            turno = turno_de(inicio.time()).value
            dia = calendario.estado_dia(sesion, fecha, turno)
            filas.append(
                {
                    "docente_id": h.docente_id,
                    "docente_nombre": h.docente.nombre,
                    "fecha": fecha,
                    "periodo_id": h.periodo_id,
                    "horario_id": h.id,
                    "bloque_id": b.id,
                    "asignatura": b.asignatura.nombre,
                    "tipo_actividad": b.asignatura.tipo,
                    "grupo": b.grupo.clave if b.grupo else b.grupo_letra,
                    "aula": b.aula.clave if b.aula else None,
                    "turno": turno,
                    "programado_inicio": inicio.time(),
                    "programado_fin": siguiente.time(),
                    "dia_habil": dia.habil,
                    "motivo_inhabil": dia.motivo,
                }
            )
            inicio = siguiente
    return filas


def _identidad(fila):
    return tuple(
        fila[c]
        for c in ("docente_id", "horario_id", "bloque_id", "programado_inicio", "programado_fin")
    )


def _cantidades(fila, registro):
    duracion = minutos(fila["programado_inicio"], fila["programado_fin"])
    resumen = dict.fromkeys(METRICAS, 0)
    resumen["programadas"] = duracion
    if registro is None and not fila["dia_habil"]:
        resumen["suspendidas"] = duracion
    else:
        resumen["exigibles"] = duracion
        if registro is None:
            resumen["pendientes"] = duracion
        else:
            resumen["cumplidas"] = registro.minutos_cumplidos
            resumen["justificadas"] = registro.minutos_justificados
            resumen["faltantes"] = (
                duracion - registro.minutos_cumplidos - registro.minutos_justificados
            )
    return resumen


def totales(filas):
    minutos_totales = {k: sum(f["minutos"][k] for f in filas) for k in METRICAS}
    return {
        "minutos": minutos_totales,
        "horas": {k: round(v / 60, 4) for k, v in minutos_totales.items()},
    }


def _fila(fila, registro, tolerancia, fuera=False):
    return {
        **fila,
        "fuera_de_programacion": fuera,
        "estado": registro.estado if registro else "pendiente" if fila["dia_habil"] else "inhabil",
        "asistencia": salida(registro) if registro else None,
        "tolerancia_minutos": tolerancia,
        "minutos": _cantidades(fila, registro),
    }


def dia(sesion, fecha, docente_id=None, turno=None, estado=None, tipo_actividad=None):
    programado = programacion(sesion, fecha)
    registros = list(sesion.scalars(select(AsistenciaHora).where(AsistenciaHora.fecha == fecha)))
    indice = {_identidad(instantanea_original(a)): a for a in registros}
    identidades = {_identidad(f) for f in programado}
    tolerancia = configuracion.tolerancia(sesion)
    filas = [_fila(f, indice.get(_identidad(f)), tolerancia) for f in programado]
    fuera = []
    for a in registros:
        copia = instantanea_original(a)
        if _identidad(copia) not in identidades:
            d = calendario.estado_dia(sesion, fecha, a.turno)
            fuera.append(
                _fila(
                    {**copia, "dia_habil": d.habil, "motivo_inhabil": d.motivo},
                    a,
                    tolerancia,
                    fuera=True,
                )
            )
    # Si el programa cambió, conservar siempre los nombres capturados al registrar.
    for f in filas:
        a = indice.get(_identidad(f))
        if a is not None:
            f.update(instantanea_original(a))
        f["bloqueada_por_registro_previo"] = any(
            a.docente_id == f["docente_id"]
            and a.programado_inicio < f["programado_fin"]
            and f["programado_inicio"] < a.programado_fin
            and _identidad(instantanea_original(a)) != _identidad(f)
            for a in registros
        )

    def filtrar(f):
        return (
            (docente_id is None or f["docente_id"] == docente_id)
            and (turno is None or f["turno"] == turno)
            and (estado is None or f["estado"] == estado)
            and (tipo_actividad is None or f["tipo_actividad"] == tipo_actividad)
        )

    filas = sorted(
        filter(filtrar, filas), key=lambda f: (f["programado_inicio"], f["docente_nombre"])
    )
    fuera = sorted(
        filter(filtrar, fuera), key=lambda f: (f["programado_inicio"], f["docente_nombre"])
    )
    legados = list(sesion.scalars(select(Asistencia).where(Asistencia.fecha == fecha)))
    desconocidos = list(
        sesion.scalars(
            select(Horario.id)
            .join(Periodo)
            .where(
                Horario.estado.in_(["vigente", "historico"]),
                Horario.vigencia_confirmada.is_(False),
                Periodo.fecha_inicio <= fecha,
                Periodo.fecha_fin >= fecha,
                Horario.docente_id == docente_id if docente_id is not None else True,
            )
        )
    )
    return {
        "fecha": fecha,
        "filas": filas,
        "registros_fuera_de_programacion": fuera,
        "totales": totales(filas),
        "totales_fuera_de_programacion": totales(fuera),
        "horarios_sin_vigencia_confirmada": desconocidos,
        "registros_por_turno_sin_convertir": [
            a.id
            for a in legados
            if (docente_id is None or a.docente_id == docente_id)
            and (turno is None or a.turno == turno)
        ],
        "aviso": "Asistencia por hora programada. Pendiente no significa falta. "
        "Los registros por turno no acreditan horas; los registros fuera del "
        "programa actual se conservan aparte y no se suman a sus totales.",
    }


def instantanea_original(a):
    return {c: getattr(a, c) for c in COPIA if c != "en_dia_inhabil"}


def salida(a):
    return {
        **instantanea_original(a),
        **{c: getattr(a, c) for c in CAMPOS},
        "id": a.id,
        "correcciones": a.correcciones,
        "en_dia_inhabil": a.en_dia_inhabil,
        "actualizado_en": a.actualizado_en,
    }


def _calcular(datos, inicio, fin):
    estado = datos["estado"]
    if estado not in ("asistio", "retardo", "falto", "justificado", "parcial"):
        raise ErrorNegocio("Estado horario inválido", 422)
    entrada, salida_real = datos.get("hora_entrada"), datos.get("hora_salida")
    for hora in (entrada, salida_real):
        if hora is not None and not _precision(hora):
            raise ErrorNegocio("Usa horas locales con precisión de minutos", 422)
    duracion = minutos(inicio, fin)
    justificados = datos.get("minutos_justificados", 0)
    if not isinstance(justificados, int) or not 0 <= justificados <= duracion:
        raise ErrorNegocio("Minutos justificados inválidos", 422)
    if estado in ("falto", "justificado"):
        if entrada is not None or salida_real is not None:
            raise ErrorNegocio("Falta y justificado no llevan horas de presencia", 422)
        cumplidos = 0
        if estado == "justificado":
            if justificados not in (0, duracion):
                raise ErrorNegocio("Usa parcial para una justificación de parte de la hora", 422)
            justificados = duracion
        elif justificados:
            raise ErrorNegocio("Una falta no lleva minutos justificados", 422)
    elif estado == "asistio":
        if (
            justificados
            or (entrada is not None and entrada != inicio)
            or (salida_real is not None and salida_real != fin)
        ):
            raise ErrorNegocio("Usa parcial o retardo si no se cumplió todo el tramo", 422)
        cumplidos = duracion
    else:
        if entrada is None or (estado == "parcial" and salida_real is None):
            raise ErrorNegocio("Indica entrada y salida de la asistencia parcial", 422)
        final = salida_real or fin
        if not inicio <= entrada < final <= fin:
            raise ErrorNegocio("La presencia debe estar dentro del tramo programado", 422)
        cumplidos = minutos(entrada, final)
        if not 0 < cumplidos < duracion or (estado == "retardo" and entrada <= inicio):
            raise ErrorNegocio("El parcial o retardo debe cumplir solo parte del tramo", 422)
        if estado == "retardo" and justificados:
            raise ErrorNegocio("Usa parcial para justificar parte del tiempo", 422)
        if cumplidos + justificados > duracion:
            raise ErrorNegocio("Presencia y justificación exceden el tiempo programado", 422)
    if justificados and not (datos.get("justificacion") or "").strip():
        raise ErrorNegocio("Indica el motivo de la justificación", 422)
    return {
        **datos,
        "minutos_cumplidos": cumplidos,
        "minutos_justificados": justificados,
        "observaciones": (datos.get("observaciones") or "").strip(),
        "justificacion": (datos.get("justificacion") or "").strip(),
    }


def _bloquear_docente(sesion, docente_id):
    # Mismo bloqueo que la confirmación de horarios: protege registro concurrente y vigencias.
    if sesion.scalar(select(Docente.id).where(Docente.id == docente_id).with_for_update()) is None:
        raise NoEncontrado("El docente")


def registrar(
    sesion,
    usuario,
    docente_id,
    fecha,
    bloque_id,
    inicio,
    datos,
    autorizar=False,
    confirmar_transaccion=True,
):
    _bloquear_docente(sesion, docente_id)
    bitacora._exigir_periodo_abierto(sesion, fecha)
    if fecha > hoy() and datos["estado"] != "justificado":
        raise ErrorNegocio("Solo se registran justificaciones en fechas futuras", 422)
    fila = next(
        (
            f
            for f in programacion(sesion, fecha)
            if f["docente_id"] == docente_id
            and f["bloque_id"] == bloque_id
            and f["programado_inicio"] == inicio
        ),
        None,
    )
    if fila is None:
        raise ErrorNegocio(
            "La hora no pertenece al horario con vigencia confirmada en esa fecha", 422
        )
    if not fila["dia_habil"]:
        if not autorizar:
            raise ErrorNegocio("Día inhábil o suspensión: requiere excepción autorizada", 409)
        if Permiso.ASISTENCIA_CORREGIR not in usuario.permisos:
            raise ErrorNegocio("La excepción requiere asistencia.corregir", 403)
    solapado = sesion.scalar(
        select(AsistenciaHora.id).where(
            AsistenciaHora.docente_id == docente_id,
            AsistenciaHora.fecha == fecha,
            AsistenciaHora.programado_inicio < fila["programado_fin"],
            AsistenciaHora.programado_fin > fila["programado_inicio"],
        )
    )
    if solapado is not None:
        raise ErrorNegocio(
            "Ya existe un registro horario que coincide o se traslapa; revisa su historial", 409
        )
    valores = _calcular(datos, fila["programado_inicio"], fila["programado_fin"])
    copia = {c: fila[c] for c in COPIA if c != "en_dia_inhabil"}
    registro = AsistenciaHora(
        **copia, **valores, en_dia_inhabil=not fila["dia_habil"], registrado_por_id=usuario.id
    )
    sesion.add(registro)
    sesion.flush()
    auditar(
        sesion,
        usuario,
        "registrar",
        "asistencia_hora",
        registro.id,
        despues=instantanea(registro, COPIA + CAMPOS),
    )
    if confirmar_transaccion:
        sesion.commit()
    return salida(registro)


def registrar_lote(sesion, usuario, entradas):
    """Una transacción, estados independientes y bloqueo ordenado por docente."""
    try:
        resultado = []
        for entrada in sorted(
            entradas, key=lambda e: (e["docente_id"], e["fecha"], e["programado_inicio"])
        ):
            identidad = {
                "docente_id",
                "fecha",
                "bloque_id",
                "programado_inicio",
                "autorizar_dia_inhabil",
            }
            resultado.append(
                registrar(
                    sesion,
                    usuario,
                    entrada["docente_id"],
                    entrada["fecha"],
                    entrada["bloque_id"],
                    entrada["programado_inicio"],
                    {k: v for k, v in entrada.items() if k not in identidad},
                    entrada.get("autorizar_dia_inhabil", False),
                    confirmar_transaccion=False,
                )
            )
        sesion.commit()
        return resultado
    except Exception:
        sesion.rollback()
        raise


def obtener(sesion, id_):
    a = sesion.get(AsistenciaHora, id_)
    if a is None:
        raise NoEncontrado("El registro horario")
    return a


def corregir(sesion, usuario, id_, cambios, motivo):
    a = obtener(sesion, id_)
    _bloquear_docente(sesion, a.docente_id)
    sesion.refresh(a)
    bitacora._exigir_periodo_abierto(sesion, a.fecha)
    if len((motivo or "").strip()) < 5:
        raise ErrorNegocio("Escribe el motivo de la corrección", 422)
    if (
        a.fecha < hoy() or a.en_dia_inhabil
    ) and Permiso.ASISTENCIA_CORREGIR not in usuario.permisos:
        raise ErrorNegocio("La corrección requiere asistencia.corregir", 403)
    if a.fecha > hoy() and cambios.get("estado", a.estado) != "justificado":
        raise ErrorNegocio("Solo se registran justificaciones en fechas futuras", 422)
    antes = instantanea(a, CAMPOS)
    datos = {**{c: getattr(a, c) for c in CAMPOS}, **cambios}
    # Al cambiar de estado, no arrastrar minutos calculados de una justificación anterior.
    if cambios.get("estado", a.estado) != a.estado and "minutos_justificados" not in cambios:
        datos["minutos_justificados"] = 0
    if cambios.get("estado", a.estado) != a.estado and datos["estado"] in (
        "asistio",
        "falto",
        "justificado",
    ):
        for campo in ("hora_entrada", "hora_salida"):
            if campo not in cambios:
                datos[campo] = None
    datos.pop("minutos_cumplidos", None)
    valores = _calcular(datos, a.programado_inicio, a.programado_fin)
    for campo in CAMPOS:
        setattr(a, campo, valores.get(campo))
    despues = instantanea(a, CAMPOS)
    if antes == despues:
        raise ErrorNegocio("No hay cambios que corregir", 422)
    a.correcciones += 1
    auditar(
        sesion,
        usuario,
        "corregir",
        "asistencia_hora",
        a.id,
        antes,
        {**despues, "motivo": motivo.strip()},
    )
    sesion.commit()
    return salida(a)


def historial(sesion, id_):
    obtener(sesion, id_)
    registros = sesion.scalars(
        select(Auditoria)
        .where(Auditoria.entidad == "asistencia_hora", Auditoria.entidad_id == str(id_))
        .order_by(Auditoria.id)
    )
    nombres = dict(sesion.execute(select(Usuario.id, Usuario.nombre)).all())
    return [
        {
            "fecha": a.fecha,
            "usuario": nombres.get(a.usuario_id, "—"),
            "accion": a.accion,
            "antes": a.antes,
            "despues": a.despues,
        }
        for a in registros
    ]


def rango(sesion, desde, hasta, **filtros):
    if hasta < desde or (hasta - desde).days >= 93:
        raise ErrorNegocio("El rango debe ser de 1 a 93 días", 422)
    dias = [
        dia(sesion, desde + timedelta(days=i), **filtros) for i in range((hasta - desde).days + 1)
    ]
    filas = [f for d in dias for f in d["filas"]]
    return {"desde": desde, "hasta": hasta, "dias": dias, "totales": totales(filas)}
