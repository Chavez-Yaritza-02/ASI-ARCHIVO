"""Incidencias importadas desde Excel: revisión, horas exactas e importación atómica.

Reglas:
- Leer el archivo NO registra asistencia: solo crea filas «pendientes» para revisar.
- Una fila se importa solo si el usuario la confirma y tiene docente, fecha válida,
  tipo y las horas exactas que no se cumplieron. Una falta reportada nunca se extiende
  sola a toda la jornada; una salida anticipada solo afecta las horas elegidas.
- Importar es todo o nada: si una hora falla (ya registrada, día inhábil, periodo
  cerrado…), no se guarda ninguna y el archivo queda igual que antes.
- Nunca se sobrescribe una asistencia existente: esa hora se informa como conflicto.
"""

import hashlib
from datetime import UTC, date, datetime, time

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.importers import incidencias_excel as lector
from app.models import (
    AsistenciaHora,
    Docente,
    Documento,
    ImportacionIncidencias,
    IncidenciaImportada,
    Periodo,
)
from app.services import asistencia_hora, documentos
from app.services.comun import ErrorNegocio, NoEncontrado, auditar, hoy, instantanea
from asi_shared import Permiso

CAMPOS = [
    "fecha",
    "docente_id",
    "docente_estado",
    "tipo",
    "hora_salida",
    "horas",
    "justificada",
    "motivo",
    "observaciones",
    "documento_id",
    "estado",
]
EDITABLES = {
    "fecha",
    "docente_id",
    "tipo",
    "hora_salida",
    "horas",
    "justificada",
    "motivo",
    "observaciones",
    "documento_id",
}
TIPOS = {"falta": "Falta", "salida_anticipada": "Salida anticipada"}


def _hm(valor: time) -> str:
    return f"{valor:%H:%M}"


def _hora(valor) -> time:
    return valor if isinstance(valor, time) else time.fromisoformat(str(valor))


# --- Carga del archivo ---------------------------------------------------------------


def cargar(sesion, usuario, contenido: bytes, nombre: str):
    """Lee el Excel y guarda sus filas como pendientes. Devuelve (importación, es_nueva).

    El mismo archivo (misma huella SHA-256) no se registra dos veces: se devuelve el
    existente. Si el archivo no se puede leer, no se guarda nada.
    """
    huella = hashlib.sha256(contenido).hexdigest()
    existente = sesion.scalar(
        select(ImportacionIncidencias).where(ImportacionIncidencias.sha256 == huella)
    )
    if existente is not None:
        return existente, False
    lectura = lector.leer(contenido)
    docentes = [(d.id, d.nombre) for d in sesion.scalars(select(Docente))]
    importacion = ImportacionIncidencias(
        nombre_archivo=(nombre or "incidencias.xlsx")[:255],
        sha256=huella,
        hoja=lectura.hoja[:100],
        usuario_id=usuario.id,
        total_filas=len(lectura.filas),
    )
    try:
        sesion.add(importacion)
        sesion.flush()
        for f in lectura.filas:
            docente_id, estado = lector.buscar_docente(f.docente_texto, docentes)
            detalle = f.detalle_texto
            if f.hora_texto:
                detalle = f"Hora: {f.hora_texto}. {detalle}".strip()
            sesion.add(
                IncidenciaImportada(
                    importacion_id=importacion.id,
                    fila=f.fila,
                    fecha_texto=f.fecha_texto,
                    docente_texto=f.docente_texto,
                    tipo_texto=f.tipo_texto,
                    detalle_texto=detalle,
                    fecha=f.fecha,
                    docente_id=docente_id,
                    docente_estado=estado,
                    tipo=f.tipo,
                    hora_salida=f.hora_salida if f.tipo != "falta" else None,
                    horas=[],
                    asistencias=[],
                    justificada=False,
                    motivo="",
                    observaciones="",
                )
            )
        sesion.flush()
        auditar(
            sesion,
            usuario,
            "importar",
            "importacion_incidencias",
            importacion.id,
            despues={
                "archivo": importacion.nombre_archivo,
                "sha256": huella,
                "hoja": importacion.hoja,
                "filas": importacion.total_filas,
                "columnas": lectura.columnas,
            },
        )
        sesion.commit()
    except IntegrityError:
        # Otro usuario subió el mismo archivo al mismo tiempo: se usa el suyo.
        sesion.rollback()
        return (
            sesion.scalar(
                select(ImportacionIncidencias).where(ImportacionIncidencias.sha256 == huella)
            ),
            False,
        )
    return importacion, True


# --- Consulta y revisión ---------------------------------------------------------------


def obtener(sesion, id_) -> ImportacionIncidencias:
    i = sesion.get(ImportacionIncidencias, id_)
    if i is None:
        raise NoEncontrado("La importación de incidencias")
    return i


def obtener_fila(sesion, id_) -> IncidenciaImportada:
    f = sesion.get(IncidenciaImportada, id_)
    if f is None:
        raise NoEncontrado("La incidencia importada")
    return f


class _Contexto:
    """Consultas repetidas durante una revisión (programa del día y registros)."""

    def __init__(self, sesion):
        self.sesion = sesion
        self._programa: dict[date, list[dict] | str] = {}

    def programa(self, fecha: date, docente_id: int) -> list[dict] | str:
        """Horas programadas del docente ese día, o el texto del error si no se pueden ver."""
        if fecha not in self._programa:
            try:
                self._programa[fecha] = asistencia_hora.programacion(self.sesion, fecha)
            except ErrorNegocio as error:
                self._programa[fecha] = error.mensaje
        programa = self._programa[fecha]
        if isinstance(programa, str):
            return programa
        return [t for t in programa if t["docente_id"] == docente_id]

    def tramo(self, fila: IncidenciaImportada, hora: dict) -> dict | None:
        programa = self.programa(fila.fecha, fila.docente_id)
        if isinstance(programa, str):
            return None
        inicio = _hora(hora["programado_inicio"])
        return next(
            (
                t
                for t in programa
                if t["bloque_id"] == hora["bloque_id"] and t["programado_inicio"] == inicio
            ),
            None,
        )


def _periodo(sesion, fecha: date) -> Periodo | None:
    return sesion.scalar(
        select(Periodo).where(Periodo.fecha_inicio <= fecha, Periodo.fecha_fin >= fecha)
    )


def registro_previsto(fila: IncidenciaImportada, tramo: dict, archivo: str) -> dict:
    """Lo que se guardará en la asistencia por hora para esta hora (sin guardarlo)."""
    inicio, fin = tramo["programado_inicio"], tramo["programado_fin"]
    origen = f"{TIPOS[fila.tipo]} reportada en Excel ({archivo}, fila {fila.fila})"
    datos = {"estado": "falto", "minutos_justificados": 0, "justificacion": ""}
    if fila.tipo == "salida_anticipada":
        salida = fila.hora_salida
        if salida >= fin:
            raise ErrorNegocio(
                f"La hora {_hm(inicio)}–{_hm(fin)} termina antes de la salida ({_hm(salida)})",
                422,
            )
        origen = (
            f"Salida anticipada a las {_hm(salida)}, reportada en Excel "
            f"({archivo}, fila {fila.fila})"
        )
        if salida > inicio:
            # Se fue a mitad de esta hora: estuvo desde el inicio hasta la salida.
            datos.update(estado="parcial", hora_entrada=inicio, hora_salida=salida)
            if fila.justificada:
                datos["minutos_justificados"] = asistencia_hora.minutos(salida, fin)
                datos["justificacion"] = fila.motivo.strip()
            datos["observaciones"] = _observaciones(origen, fila)
            return datos
    if fila.justificada:
        datos.update(estado="justificado", justificacion=fila.motivo.strip())
    datos["observaciones"] = _observaciones(origen, fila)
    return datos


def _observaciones(origen: str, fila: IncidenciaImportada) -> str:
    return ". ".join(x for x in (origen, fila.observaciones.strip()) if x)[:1000]


def _se_traslapan(a: list[dict], b: list[dict]) -> bool:
    return bool(
        {(h["bloque_id"], h["programado_inicio"]) for h in a}
        & {(h["bloque_id"], h["programado_inicio"]) for h in b}
    )


def revisar(sesion, fila: IncidenciaImportada, contexto: _Contexto | None = None):
    """(problemas que impiden importar, avisos informativos)."""
    contexto = contexto or _Contexto(sesion)
    problemas: list[str] = []
    avisos: list[str] = []
    if fila.docente_id is None:
        problemas.append(f"Docente no encontrado en el catálogo: «{fila.docente_texto}»")
    elif fila.docente_estado == "sugerido":
        problemas.append("Confirma el docente sugerido")
    if fila.fecha is None:
        problemas.append(f"Fecha incorrecta o ilegible: «{fila.fecha_texto}»")
    else:
        periodo = _periodo(sesion, fila.fecha)
        if fila.fecha > hoy():
            problemas.append("La fecha es futura")
        if periodo is None:
            problemas.append("La fecha no pertenece a ningún periodo registrado")
        elif periodo.estado == "cerrado":
            problemas.append(f"El periodo {periodo.nombre} está cerrado")
    if fila.tipo is None:
        problemas.append("Indica si es falta o salida anticipada")
    elif fila.tipo == "salida_anticipada" and fila.hora_salida is None:
        problemas.append("Indica la hora de salida")
    if fila.justificada and not fila.motivo.strip():
        problemas.append("Escribe el motivo de la justificación")

    if fila.docente_id is not None and fila.fecha is not None:
        programa = contexto.programa(fila.fecha, fila.docente_id)
        if isinstance(programa, str):
            problemas.append(programa)
        elif not programa:
            problemas.append(
                "El docente no tiene horas programadas ese día (revisa la fecha o su horario)"
            )
        if not fila.horas:
            problemas.append("Elige las horas que no se cumplieron")
        registros = sesion.scalars(
            select(AsistenciaHora).where(
                AsistenciaHora.docente_id == fila.docente_id, AsistenciaHora.fecha == fila.fecha
            )
        ).all()
        for h in fila.horas:
            tramo = None if isinstance(programa, str) else contexto.tramo(fila, h)
            if tramo is None:
                problemas.append(
                    f"La hora de las {str(h['programado_inicio'])[:5]} ya no está en el horario"
                )
                continue
            if not tramo["dia_habil"]:
                problemas.append(
                    f"Día inhábil ({tramo['motivo_inhabil'] or 'suspensión'}): no se registra "
                    "la incidencia sin una excepción autorizada en Asistencia por hora"
                )
            ocupado = next(
                (
                    r
                    for r in registros
                    if r.programado_inicio < tramo["programado_fin"]
                    and tramo["programado_inicio"] < r.programado_fin
                    and r.id not in (fila.asistencias or [])
                ),
                None,
            )
            if ocupado is not None and fila.estado == "pendiente":
                problemas.append(
                    f"{_hm(tramo['programado_inicio'])}–{_hm(tramo['programado_fin'])} ya tiene "
                    f"registro ({ocupado.estado}); no se sobrescribe: corrígelo en "
                    "Asistencia por hora si hace falta"
                )
            if fila.tipo and (fila.tipo != "salida_anticipada" or fila.hora_salida):
                try:
                    registro_previsto(fila, tramo, "")
                except ErrorNegocio as error:
                    problemas.append(error.mensaje)

        otras = sesion.scalars(
            select(IncidenciaImportada).where(
                IncidenciaImportada.id != fila.id,
                IncidenciaImportada.docente_id == fila.docente_id,
                IncidenciaImportada.fecha == fila.fecha,
                IncidenciaImportada.tipo == fila.tipo,
                IncidenciaImportada.estado != "descartada",
            )
        ).all()
        for o in otras:
            donde = (
                f"fila {o.fila}"
                if o.importacion_id == fila.importacion_id
                else f"fila {o.fila} de otro archivo (importación {o.importacion_id})"
            )
            texto = f"Posible duplicado: la {donde} es la misma incidencia ({o.estado})"
            if not o.horas or not fila.horas or _se_traslapan(o.horas, fila.horas):
                problemas.append(texto + "; descarta una de las dos")
            else:
                avisos.append(texto + " pero con otras horas")
    if fila.documento_id is not None:
        d = sesion.get(Documento, fila.documento_id)
        if d is None or not d.activo:
            problemas.append("El justificante elegido no existe o está archivado")
        elif d.docente_id is not None and d.docente_id != fila.docente_id:
            problemas.append("El justificante elegido corresponde a otro docente")
    return list(dict.fromkeys(problemas)), avisos


def salida(sesion, fila: IncidenciaImportada, contexto: _Contexto | None = None) -> dict:
    problemas, avisos = revisar(sesion, fila, contexto) if fila.estado == "pendiente" else ([], [])
    return {
        "id": fila.id,
        "importacion_id": fila.importacion_id,
        "fila": fila.fila,
        "fecha_texto": fila.fecha_texto,
        "docente_texto": fila.docente_texto,
        "tipo_texto": fila.tipo_texto,
        "detalle_texto": fila.detalle_texto,
        "fecha": fila.fecha,
        "docente": {"id": fila.docente.id, "nombre": fila.docente.nombre} if fila.docente else None,
        "docente_estado": fila.docente_estado,
        "tipo": fila.tipo,
        "hora_salida": fila.hora_salida,
        "horas": fila.horas or [],
        "justificada": fila.justificada,
        "motivo": fila.motivo,
        "observaciones": fila.observaciones,
        "documento_id": fila.documento_id,
        "estado": fila.estado,
        "asistencias": fila.asistencias or [],
        "importada_en": fila.importada_en,
        "problemas": problemas,
        "avisos": avisos,
        "lista": fila.estado == "pendiente" and not problemas,
    }


def resumen(sesion, i: ImportacionIncidencias) -> dict:
    conteo = dict(
        sesion.execute(
            select(IncidenciaImportada.estado, func.count())
            .where(IncidenciaImportada.importacion_id == i.id)
            .group_by(IncidenciaImportada.estado)
        ).all()
    )
    return {
        "id": i.id,
        "nombre_archivo": i.nombre_archivo,
        "hoja": i.hoja,
        "total_filas": i.total_filas,
        "creado_en": i.creado_en,
        "pendientes": conteo.get("pendiente", 0),
        "importadas": conteo.get("importada", 0),
        "descartadas": conteo.get("descartada", 0),
    }


def detalle(sesion, i: ImportacionIncidencias) -> dict:
    contexto = _Contexto(sesion)
    filas = [salida(sesion, f, contexto) for f in i.filas]
    return {
        **resumen(sesion, i),
        "filas": filas,
        "listas": sum(f["lista"] for f in filas),
        "aviso": "Leer el archivo no registra asistencia. Solo se importan las filas que "
        "confirmes, con las horas exactas que elijas; las demás quedan pendientes.",
    }


def listar(sesion) -> list[dict]:
    return [
        resumen(sesion, i)
        for i in sesion.scalars(
            select(ImportacionIncidencias).order_by(ImportacionIncidencias.id.desc())
        )
    ]


def horas(sesion, fila_id: int) -> dict:
    """Horas programadas del docente ese día, su estado y lo que se registraría."""
    fila = obtener_fila(sesion, fila_id)
    if fila.docente_id is None or fila.fecha is None:
        return {"fila": salida(sesion, fila), "horas": []}
    elegidas = {(h["bloque_id"], _hora(h["programado_inicio"])) for h in fila.horas or []}
    dia = asistencia_hora.dia(sesion, fila.fecha, docente_id=fila.docente_id)
    archivo = fila.importacion.nombre_archivo
    resultado = []
    for t in dia["filas"]:
        clave = (t["bloque_id"], t["programado_inicio"])
        previsto = None
        if fila.tipo and (fila.tipo != "salida_anticipada" or fila.hora_salida):
            try:
                previsto = registro_previsto(fila, t, archivo)
            except ErrorNegocio as error:
                previsto = {"error": error.mensaje}
        resultado.append(
            {
                "bloque_id": t["bloque_id"],
                "programado_inicio": t["programado_inicio"],
                "programado_fin": t["programado_fin"],
                "asignatura": t["asignatura"],
                "grupo": t["grupo"],
                "aula": t["aula"],
                "dia_habil": t["dia_habil"],
                "motivo_inhabil": t["motivo_inhabil"],
                "estado": t["estado"],
                "registrada": t["asistencia"] is not None,
                "seleccionada": clave in elegidas,
                # Solo una sugerencia visible: nada se marca sin que el usuario lo elija.
                "sugerida": fila.tipo == "salida_anticipada"
                and fila.hora_salida is not None
                and fila.hora_salida < t["programado_fin"],
                "se_registrara": previsto,
            }
        )
    return {"fila": salida(sesion, fila), "horas": resultado}


# --- Correcciones ------------------------------------------------------------------


def _exigir_pendiente(fila: IncidenciaImportada) -> None:
    if fila.estado != "pendiente":
        raise ErrorNegocio(
            f"La fila {fila.fila} está {fila.estado}: solo se corrigen filas pendientes", 409
        )


def _horas_validas(valor) -> list[dict]:
    if not isinstance(valor, list):
        raise ErrorNegocio("Las horas deben ser una lista", 422)
    vistas, salida_ = set(), []
    for h in valor:
        try:
            clave = (int(h["bloque_id"]), _hora(h["programado_inicio"]))
        except (KeyError, TypeError, ValueError) as error:
            raise ErrorNegocio("Hora elegida inválida", 422) from error
        if clave not in vistas:
            vistas.add(clave)
            salida_.append({"bloque_id": clave[0], "programado_inicio": clave[1].isoformat()})
    return sorted(salida_, key=lambda h: h["programado_inicio"])


def editar(sesion, usuario, fila_id: int, cambios: dict) -> IncidenciaImportada:
    fila = obtener_fila(sesion, fila_id)
    _exigir_pendiente(fila)
    desconocidos = set(cambios) - EDITABLES
    if desconocidos:
        raise ErrorNegocio(f"Campos no editables: {', '.join(sorted(desconocidos))}", 422)
    antes = instantanea(fila, CAMPOS)
    if "docente_id" in cambios:
        docente_id = cambios["docente_id"]
        if docente_id is not None and sesion.get(Docente, docente_id) is None:
            raise NoEncontrado("El docente")
        if docente_id != fila.docente_id and "horas" not in cambios:
            fila.horas = []  # las horas elegidas eran de otro docente
        fila.docente_id = docente_id
        fila.docente_estado = "confirmado" if docente_id is not None else "sin_coincidencia"
    if "fecha" in cambios:
        if cambios["fecha"] != fila.fecha and "horas" not in cambios:
            fila.horas = []  # las horas elegidas eran de otro día
        fila.fecha = cambios["fecha"]
    if "tipo" in cambios:
        if cambios["tipo"] not in (None, *TIPOS):
            raise ErrorNegocio("Tipo de incidencia inválido", 422)
        fila.tipo = cambios["tipo"]
    if "hora_salida" in cambios:
        fila.hora_salida = cambios["hora_salida"]
    if fila.tipo == "falta":
        fila.hora_salida = None
    if "horas" in cambios:
        fila.horas = _horas_validas(cambios["horas"])
    for campo in ("justificada", "motivo", "observaciones"):
        if campo in cambios:
            setattr(fila, campo, cambios[campo] if campo == "justificada" else cambios[campo] or "")
    if "documento_id" in cambios:
        if (
            cambios["documento_id"] is not None
            and sesion.get(Documento, cambios["documento_id"]) is None
        ):
            raise NoEncontrado("El justificante")
        fila.documento_id = cambios["documento_id"]
    despues = instantanea(fila, CAMPOS)
    if antes == despues:
        raise ErrorNegocio("No hay cambios que guardar", 422)
    auditar(sesion, usuario, "editar", "incidencia_importada", fila.id, antes, despues)
    sesion.commit()
    return fila


def cambiar_estado(sesion, usuario, fila_id: int, descartar: bool, motivo: str = ""):
    fila = obtener_fila(sesion, fila_id)
    if descartar:
        _exigir_pendiente(fila)
        if len(motivo.strip()) < 5:
            raise ErrorNegocio("Escribe el motivo para descartar la fila", 422)
        nuevo = "descartada"
    else:
        if fila.estado != "descartada":
            raise ErrorNegocio("Solo se recuperan filas descartadas", 409)
        nuevo = "pendiente"
    antes = {"estado": fila.estado}
    fila.estado = nuevo
    auditar(
        sesion,
        usuario,
        "descartar" if descartar else "recuperar",
        "incidencia_importada",
        fila.id,
        antes,
        {"estado": nuevo, "motivo": motivo.strip()},
    )
    sesion.commit()
    return fila


# --- Importación -----------------------------------------------------------------------


def importar(sesion, usuario, importacion_id: int, fila_ids: list[int]) -> dict:
    """Registra en la asistencia por hora SOLO las filas confirmadas. Todo o nada."""
    if Permiso.ASISTENCIA_CORREGIR not in usuario.permisos:
        raise ErrorNegocio(
            "Importar incidencias de días anteriores requiere asistencia.corregir", 403
        )
    importacion = obtener(sesion, importacion_id)
    if not fila_ids:
        raise ErrorNegocio("Elige al menos una fila confirmada", 422)
    filas = []
    for id_ in sorted(set(fila_ids)):
        fila = obtener_fila(sesion, id_)
        if fila.importacion_id != importacion.id:
            raise ErrorNegocio(f"La fila {id_} es de otra importación", 422)
        _exigir_pendiente(fila)
        filas.append(fila)
    contexto = _Contexto(sesion)
    problemas = [f"Fila {f.fila}: {p}" for f in filas for p in revisar(sesion, f, contexto)[0]]
    if problemas:
        raise ErrorNegocio("Corrige las filas antes de importar; no se guardó nada", 422, problemas)

    archivo = importacion.nombre_archivo
    actual = None
    resultado = []
    try:
        for fila in filas:
            actual = fila.fila
            ids = []
            for h in fila.horas:
                tramo = contexto.tramo(fila, h)
                registro = asistencia_hora.registrar(
                    sesion,
                    usuario,
                    fila.docente_id,
                    fila.fecha,
                    h["bloque_id"],
                    tramo["programado_inicio"],
                    registro_previsto(fila, tramo, archivo),
                    confirmar_transaccion=False,
                )
                ids.append(registro["id"])
                if fila.documento_id is not None:
                    documentos.vincular(
                        sesion,
                        usuario,
                        fila.documento_id,
                        None,
                        registro["id"],
                        f"Justificante de la incidencia importada ({archivo}, fila {fila.fila})",
                        confirmar_transaccion=False,
                    )
            fila.estado = "importada"
            fila.asistencias = ids
            fila.importada_por_id = usuario.id
            fila.importada_en = datetime.now(UTC)
            auditar(
                sesion,
                usuario,
                "importar_fila",
                "incidencia_importada",
                fila.id,
                {"estado": "pendiente"},
                {"estado": "importada", "asistencias": ids, "horas": fila.horas, "tipo": fila.tipo},
            )
            resultado.append({"fila": fila.fila, "asistencias": ids})
        sesion.commit()
    except ErrorNegocio as error:
        sesion.rollback()
        raise ErrorNegocio(
            "No se importó nada: " + error.mensaje,
            error.estado_http,
            [f"Fila {actual}: {error.mensaje}", *error.problemas],
        ) from error
    except Exception:
        sesion.rollback()
        raise
    return {"importadas": resultado, "horas": sum(len(r["asistencias"]) for r in resultado)}
