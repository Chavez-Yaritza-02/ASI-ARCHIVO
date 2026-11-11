"""Endpoints de bitácora, asistencias, incidencias, calendario y reportes."""

from datetime import date, datetime, time
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field

from app.api.deps import SesionDB, requiere_permiso
from app.models import Usuario
from app.reports import bitacora as reportes
from app.schemas.horarios import Referencia
from app.services import bitacora as servicio
from app.services import calendario as servicio_calendario
from asi_shared import Permiso, TipoEventoCalendario, TipoIncidencia, Turno

Lector = Annotated[Usuario, Depends(requiere_permiso(Permiso.ASISTENCIA_VER))]
Registrador = Annotated[Usuario, Depends(requiere_permiso(Permiso.ASISTENCIA_REGISTRAR))]
GestorCalendario = Annotated[Usuario, Depends(requiere_permiso(Permiso.PERIODOS_GESTIONAR))]
Reportero = Annotated[Usuario, Depends(requiere_permiso(Permiso.REPORTES_GENERAR))]
EstadoRegistro = Literal["asistio", "retardo", "falto", "justificado"]

bitacora = APIRouter(prefix="/bitacora", tags=["bitácora"])
asistencias = APIRouter(prefix="/asistencias", tags=["bitácora"])
incidencias = APIRouter(prefix="/incidencias", tags=["bitácora"])
calendario = APIRouter(prefix="/calendario", tags=["calendario"])


# --- Esquemas ------------------------------------------------------------------------------


class Actividad(BaseModel):
    asignatura: str
    grupo: str | None
    aula: str | None
    inicio: time
    fin: time


class RegistroSalida(BaseModel):
    id: int
    estado: str
    hora_entrada: time | None
    hora_salida: time | None
    observaciones: str
    justificacion: str
    en_dia_inhabil: bool
    correcciones: int
    actualizado_en: datetime


class FilaBitacora(BaseModel):
    docente: Referencia
    turno: Turno
    programado_inicio: time | None
    programado_fin: time | None
    actividades: list[Actividad]
    horario_id: int | None
    estado: str
    dia_habil: bool
    motivo_inhabil: str
    fuera_de_programacion: bool
    asistencia: RegistroSalida | None
    minutos_retardo: int | None
    tolerancia_minutos: int


class IncidenciaSalida(BaseModel):
    id: int
    fecha: date
    docente: Referencia | None
    turno: Turno | None
    tipo: TipoIncidencia
    descripcion: str


class PeriodoBreve(BaseModel):
    id: int
    nombre: str
    estado: str


class Bitacora(BaseModel):
    fecha: date
    periodo: PeriodoBreve | None
    dia_habil: bool
    motivo: str
    filas: list[FilaBitacora]
    resumen: dict[str, int]
    incidencias: list[IncidenciaSalida]


class RegistroEntrada(BaseModel):
    docente_id: int
    fecha: date
    turno: Turno
    estado: EstadoRegistro
    hora_entrada: time | None = None
    hora_salida: time | None = None
    observaciones: str = Field(default="", max_length=1000)
    justificacion: str = Field(default="", max_length=1000)
    autorizar_dia_inhabil: bool = Field(
        default=False, description="Excepción autorizada (requiere asistencia.corregir)"
    )


class CorreccionEntrada(BaseModel):
    motivo: str = Field(min_length=5, max_length=500)
    estado: EstadoRegistro | None = None
    hora_entrada: time | None = None
    hora_salida: time | None = None
    observaciones: str | None = Field(default=None, max_length=1000)
    justificacion: str | None = Field(default=None, max_length=1000)


class CambioHistorial(BaseModel):
    fecha: datetime
    usuario: str
    accion: str
    antes: dict | None
    despues: dict | None


class IncidenciaEntrada(BaseModel):
    fecha: date
    docente_id: int | None = None
    turno: Turno | None = None
    tipo: TipoIncidencia
    descripcion: str = Field(min_length=3, max_length=2000)


class IncidenciaEdicion(BaseModel):
    tipo: TipoIncidencia | None = None
    turno: Turno | None = None
    descripcion: str | None = Field(default=None, min_length=3, max_length=2000)


class EventoEntrada(BaseModel):
    tipo: TipoEventoCalendario
    fecha_inicio: date
    fecha_fin: date
    turno: Turno | None = None
    descripcion: str = Field(min_length=3, max_length=200)


class EventoSalida(EventoEntrada):
    id: int
    activo: bool


# --- Conversión ------------------------------------------------------------------------


def _incidencia(i) -> IncidenciaSalida:
    return IncidenciaSalida(
        id=i.id,
        fecha=i.fecha,
        turno=i.turno,
        tipo=i.tipo,
        descripcion=i.descripcion,
        docente=Referencia(id=i.docente.id, nombre=i.docente.nombre) if i.docente else None,
    )


def _bitacora(datos: dict) -> Bitacora:
    return Bitacora(**{**datos, "incidencias": [_incidencia(i) for i in datos["incidencias"]]})


# --- Bitácora ---------------------------------------------------------------------------


@bitacora.get("", response_model=Bitacora)
def bitacora_del_dia(
    sesion: SesionDB,
    _: Lector,
    fecha: date,
    turno: Turno | None = None,
    docente_id: int | None = None,
    estado: Annotated[str | None, Query(description="pendiente, asistio, retardo…")] = None,
):
    """Docentes programados en la fecha (según el horario vigente ese día) y sus registros."""
    return _bitacora(servicio.dia(sesion, fecha, turno, docente_id, estado))


def _archivo(contenido: bytes, formato: str, nombre: str) -> Response:
    tipos = {
        "pdf": "application/pdf",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }
    return Response(
        content=contenido,
        media_type=tipos[formato],
        headers={"Content-Disposition": f'attachment; filename="{nombre}.{formato}"'},
    )


@bitacora.get("/exportar", response_class=Response)
def exportar_dia(
    sesion: SesionDB,
    _: Reportero,
    fecha: date,
    formato: Literal["pdf", "xlsx"] = "pdf",
    turno: Turno | None = None,
):
    """Bitácora del día lista para imprimir (PDF con firmas) o para Excel."""
    datos = servicio.dia(sesion, fecha, turno)
    subtitulo = reportes.fecha_larga(fecha)
    if datos["periodo"]:
        subtitulo += f" · Periodo {datos['periodo']['nombre']}"
    if turno:
        subtitulo += f" · Turno {turno}"
    if not datos["dia_habil"]:
        subtitulo += f" · {datos['motivo']}"
    generador = reportes.pdf if formato == "pdf" else reportes.xlsx
    contenido = generador(
        "Bitácora diaria de asistencia docente", subtitulo, [datos], datos["incidencias"]
    )
    return _archivo(contenido, formato, f"bitacora_{fecha.isoformat()}")


@bitacora.get("/reporte", response_class=Response)
def reporte_rango(
    sesion: SesionDB,
    _: Reportero,
    desde: date,
    hasta: date,
    formato: Literal["pdf", "xlsx"] = "pdf",
    docente_id: int | None = None,
    turno: Turno | None = None,
):
    """Reporte por rango de fechas, con filtros por docente y turno."""
    dias = servicio.rango(sesion, desde, hasta, docente_id, turno)
    incidencias_rango = servicio.listar_incidencias(sesion, desde, hasta, docente_id)
    subtitulo = f"Del {desde:%d/%m/%Y} al {hasta:%d/%m/%Y}"
    filas = [f for d in dias for f in d["filas"]]
    if docente_id and filas:
        subtitulo += f" · {filas[0]['docente']['nombre']}"
    if turno:
        subtitulo += f" · Turno {turno}"
    generador = reportes.pdf if formato == "pdf" else reportes.xlsx
    contenido = generador("Reporte de asistencia docente", subtitulo, dias, incidencias_rango)
    return _archivo(contenido, formato, f"asistencia_{desde.isoformat()}_{hasta.isoformat()}")


# --- Asistencias ------------------------------------------------------------------------


@asistencias.post("", response_model=RegistroSalida, status_code=201)
def registrar(datos: RegistroEntrada, sesion: SesionDB, usuario: Registrador):
    campos = datos.model_dump(
        include={"estado", "hora_entrada", "hora_salida", "observaciones", "justificacion"}
    )
    return servicio.registrar(
        sesion,
        usuario,
        datos.docente_id,
        datos.fecha,
        datos.turno,
        campos,
        datos.autorizar_dia_inhabil,
    )


@asistencias.patch("/{id_}", response_model=RegistroSalida)
def corregir(id_: int, datos: CorreccionEntrada, sesion: SesionDB, usuario: Registrador):
    """Corrige un registro (siempre con motivo). Días anteriores: asistencia.corregir."""
    cambios = datos.model_dump(exclude_unset=True, exclude={"motivo"})
    return servicio.corregir(sesion, usuario, id_, cambios, datos.motivo)


@asistencias.get("/{id_}/historial", response_model=list[CambioHistorial])
def historial(id_: int, sesion: SesionDB, _: Lector):
    return servicio.historial(sesion, id_)


# --- Incidencias ------------------------------------------------------------------------


@incidencias.get("", response_model=list[IncidenciaSalida])
def listar_incidencias(
    sesion: SesionDB, _: Lector, desde: date, hasta: date, docente_id: int | None = None
):
    return [_incidencia(i) for i in servicio.listar_incidencias(sesion, desde, hasta, docente_id)]


@incidencias.post("", response_model=IncidenciaSalida, status_code=201)
def crear_incidencia(datos: IncidenciaEntrada, sesion: SesionDB, usuario: Registrador):
    return _incidencia(servicio.crear_incidencia(sesion, usuario, datos.model_dump()))


@incidencias.patch("/{id_}", response_model=IncidenciaSalida)
def editar_incidencia(id_: int, datos: IncidenciaEdicion, sesion: SesionDB, usuario: Registrador):
    return _incidencia(
        servicio.editar_incidencia(sesion, usuario, id_, datos.model_dump(exclude_unset=True))
    )


@incidencias.post("/{id_}/anular", response_model=IncidenciaSalida)
def anular_incidencia(id_: int, sesion: SesionDB, usuario: Registrador):
    return _incidencia(servicio.editar_incidencia(sesion, usuario, id_, {"anulada": True}))


# --- Calendario -------------------------------------------------------------------------


@calendario.get("", response_model=list[EventoSalida])
def listar_eventos(
    sesion: SesionDB,
    _: Lector,
    desde: date | None = None,
    hasta: date | None = None,
    incluir_anulados: bool = False,
):
    return servicio_calendario.listar(sesion, desde, hasta, incluir_anulados)


@calendario.post("", response_model=EventoSalida, status_code=201)
def crear_evento(datos: EventoEntrada, sesion: SesionDB, usuario: GestorCalendario):
    return servicio_calendario.crear(sesion, usuario, datos.model_dump())


@calendario.put("/{id_}", response_model=EventoSalida)
def editar_evento(id_: int, datos: EventoEntrada, sesion: SesionDB, usuario: GestorCalendario):
    return servicio_calendario.editar(sesion, usuario, id_, datos.model_dump())


@calendario.post("/{id_}/anular", response_model=EventoSalida)
def anular_evento(id_: int, sesion: SesionDB, usuario: GestorCalendario):
    return servicio_calendario.editar(sesion, usuario, id_, {"activo": False})
