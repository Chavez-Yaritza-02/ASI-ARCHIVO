"""Endpoints de importación de horarios desde PDF (zona de revisión).

Todo requiere `horarios.editar`: la importación contiene datos sin revisar y solo crea
borradores. Confirmar la versión vigente sigue en /horarios/{id}/confirmar.
"""

from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, sessionmaker

from app.api.deps import SesionDB, requiere_permiso
from app.db.sesion import obtener_engine
from app.models import DocumentoImportado, Importacion, PaginaImportada, Periodo, Usuario
from app.schemas.horarios import ORDEN_DIAS, HorarioDetalle, Referencia, detalle
from app.services import importacion as servicio
from asi_shared import DiaSemana, Permiso

router = APIRouter(prefix="/importaciones", tags=["importación"])
Editor = Annotated[Usuario, Depends(requiere_permiso(Permiso.HORARIOS_EDITAR))]


# --- Esquemas ----------------------------------------------------------------------


class PaginaResumen(BaseModel):
    id: int
    documento: str
    numero: int
    estado: str
    mensaje: str
    docente_texto: str
    docente: Referencia | None
    docente_estado: str
    version_documento: int | None
    fecha_documento: date | None
    horas_qr: int | None
    celdas: int
    pendientes: int
    horario_id: int | None
    duplicado_de_id: int | None


class CeldaSalida(BaseModel):
    id: int
    dia: DiaSemana
    hora: int
    origen: str
    texto_ocr: str
    actividad_texto: str
    grupo_texto: str | None
    aula_texto: str | None
    asignatura_id: int | None
    asignatura_estado: str
    aula_id: int | None
    aula_estado: str
    grupo_id: int | None
    grupo_letra: str | None
    grupo_estado: str


class PaginaDetalle(PaginaResumen):
    importacion_id: int
    periodo_id: int
    nomina: str | None
    periodo_texto: str | None
    lista_pendientes: list[str]
    avisos: list[str]
    celdas_detalle: list[CeldaSalida]


class DocumentoSalida(BaseModel):
    id: int
    nombre_archivo: str
    estado: str
    mensaje: str
    paginas: list[PaginaResumen]
    original_importacion_id: int | None = Field(
        default=None, description="Si es un PDF ya importado: importación con sus páginas"
    )


class ImportacionSalida(BaseModel):
    id: int
    periodo: Referencia
    nombre_archivo: str
    estado: str
    mensaje: str
    total_documentos: int
    procesados: int
    creado_en: datetime
    conteo: dict[str, int]


class ImportacionDetalle(ImportacionSalida):
    documentos: list[DocumentoSalida]


class CeldaEntrada(BaseModel):
    id: int | None = Field(default=None, description="Celda leída por OCR que se conserva")
    dia: DiaSemana
    hora: int = Field(ge=7, le=22)
    asignatura_id: int | None
    aula_id: int | None = None
    grupo_id: int | None = None
    grupo_letra: str | None = Field(default=None, max_length=5)
    confirmar: bool = Field(default=False, description="Acepta los valores mostrados")


class RevisionEntrada(BaseModel):
    docente_id: int | None = None
    celdas: list[CeldaEntrada] | None = None


class AprobacionEntrada(BaseModel):
    aceptar_diferencia_horas: bool = False
    permitir_duplicado: bool = False


# --- Conversión --------------------------------------------------------------------


def _resumen_pagina(sesion: Session, p: PaginaImportada) -> PaginaResumen:
    return PaginaResumen(
        id=p.id,
        documento=p.documento.nombre_archivo,
        numero=p.numero,
        estado=p.estado,
        mensaje=p.mensaje,
        docente_texto=p.docente_texto,
        docente=Referencia.model_validate(p.docente) if p.docente else None,
        docente_estado=p.docente_estado,
        version_documento=p.version_documento,
        fecha_documento=p.fecha_documento,
        horas_qr=p.horas_qr,
        celdas=len(p.celdas),
        pendientes=len(servicio.pendientes(sesion, p)) if p.estado == "por_revisar" else 0,
        horario_id=p.horario_id,
        duplicado_de_id=p.duplicado_de_id,
    )


def _detalle_pagina(sesion: Session, p: PaginaImportada) -> PaginaDetalle:
    return PaginaDetalle(
        **_resumen_pagina(sesion, p).model_dump(),
        importacion_id=p.documento.importacion_id,
        periodo_id=p.documento.importacion.periodo_id,
        nomina=p.nomina,
        periodo_texto=p.periodo_texto,
        lista_pendientes=servicio.pendientes(sesion, p) if p.estado == "por_revisar" else [],
        avisos=servicio.avisos(sesion, p),
        celdas_detalle=[
            CeldaSalida(
                **{k: getattr(c, k) for k in CeldaSalida.model_fields if k not in ("dia",)},
                dia=ORDEN_DIAS[c.dia],
            )
            for c in p.celdas
        ],
    )


def _salida(sesion: Session, i: Importacion, con_documentos: bool):
    conteo: dict[str, int] = {}
    for d in i.documentos:
        for p in d.paginas:
            conteo[p.estado] = conteo.get(p.estado, 0) + 1
    base = {
        "id": i.id,
        "periodo": Referencia(id=i.periodo_id, nombre=_periodo_nombre(sesion, i.periodo_id)),
        "nombre_archivo": i.nombre_archivo,
        "estado": i.estado,
        "mensaje": i.mensaje,
        "total_documentos": i.total_documentos,
        "procesados": i.procesados,
        "creado_en": i.creado_en,
        "conteo": conteo,
    }
    if not con_documentos:
        return ImportacionSalida(**base)
    return ImportacionDetalle(
        **base,
        documentos=[
            DocumentoSalida(
                id=d.id,
                nombre_archivo=d.nombre_archivo,
                estado=d.estado,
                mensaje=d.mensaje,
                paginas=[_resumen_pagina(sesion, p) for p in d.paginas],
                original_importacion_id=_importacion_original(sesion, d),
            )
            for d in i.documentos
        ],
    )


def _importacion_original(sesion: Session, d: DocumentoImportado) -> int | None:
    if d.duplicado_de_id is None:
        return None
    original = sesion.get(DocumentoImportado, d.duplicado_de_id)
    return original.importacion_id if original else None


def _periodo_nombre(sesion: Session, periodo_id: int) -> str:
    return sesion.get(Periodo, periodo_id).nombre


def _procesar_en_segundo_plano(importacion_id: int, trabajos: list[tuple[int, bytes]]) -> None:
    fabrica = sessionmaker(bind=obtener_engine(), expire_on_commit=False)
    with fabrica() as sesion:
        servicio.procesar(sesion, importacion_id, trabajos)


# --- Rutas ---------------------------------------------------------------------------


@router.post("", response_model=ImportacionSalida, status_code=202)
async def importar(
    sesion: SesionDB,
    usuario: Editor,
    tareas: BackgroundTasks,
    archivo: Annotated[UploadFile, File(description="ZIP con PDFs o un PDF")],
    periodo_id: Annotated[int, Form()],
):
    """Recibe el archivo y responde de inmediato; el OCR sigue en segundo plano.
    Consulta GET /importaciones/{id} para ver el avance."""
    contenido = await archivo.read(servicio.TAMANO_MAXIMO + 1)
    importacion, trabajos = servicio.iniciar(
        sesion, usuario, periodo_id, archivo.filename or "archivo", contenido
    )
    if trabajos:
        tareas.add_task(_procesar_en_segundo_plano, importacion.id, trabajos)
    else:
        importacion.estado = "terminada"
        importacion.mensaje = "Todos los PDF ya se habían importado"
        sesion.commit()
    return _salida(sesion, importacion, con_documentos=False)


@router.get("", response_model=list[ImportacionSalida])
def listar(sesion: SesionDB, _: Editor):
    return [_salida(sesion, i, con_documentos=False) for i in servicio.listar(sesion)]


@router.get("/{id_}", response_model=ImportacionDetalle)
def consultar(id_: int, sesion: SesionDB, _: Editor):
    return _salida(sesion, servicio.obtener(sesion, id_), con_documentos=True)


@router.post("/{id_}/cancelar", response_model=ImportacionSalida)
def cancelar(id_: int, sesion: SesionDB, usuario: Editor):
    return _salida(sesion, servicio.cancelar(sesion, usuario, id_), con_documentos=False)


@router.get("/paginas/{id_}", response_model=PaginaDetalle)
def consultar_pagina(id_: int, sesion: SesionDB, _: Editor):
    return _detalle_pagina(sesion, servicio.obtener_pagina(sesion, id_))


@router.put("/paginas/{id_}", response_model=PaginaDetalle)
def guardar_revision(id_: int, datos: RevisionEntrada, sesion: SesionDB, usuario: Editor):
    celdas = None
    if datos.celdas is not None:
        celdas = [
            servicio.CeldaRevisada(
                dia=ORDEN_DIAS.index(c.dia),
                hora=c.hora,
                asignatura_id=c.asignatura_id,
                aula_id=c.aula_id,
                grupo_id=c.grupo_id,
                grupo_letra=c.grupo_letra,
                id=c.id,
                confirmar=c.confirmar,
            )
            for c in datos.celdas
        ]
    pagina = servicio.guardar_revision(sesion, usuario, id_, datos.docente_id, celdas)
    return _detalle_pagina(sesion, pagina)


@router.post("/paginas/{id_}/aceptar-sugerencias", response_model=PaginaDetalle)
def aceptar_sugerencias(id_: int, sesion: SesionDB, usuario: Editor):
    return _detalle_pagina(sesion, servicio.aceptar_sugerencias(sesion, usuario, id_))


@router.post("/paginas/{id_}/aprobar", response_model=HorarioDetalle)
def aprobar(id_: int, datos: AprobacionEntrada, sesion: SesionDB, usuario: Editor):
    """Crea un horario en *borrador* con lo revisado (no lo vuelve vigente)."""
    horario = servicio.aprobar(
        sesion, usuario, id_, datos.aceptar_diferencia_horas, datos.permitir_duplicado
    )
    return detalle(horario)


@router.post("/paginas/{id_}/descartar", response_model=PaginaDetalle)
def descartar(id_: int, sesion: SesionDB, usuario: Editor):
    return _detalle_pagina(sesion, servicio.descartar(sesion, usuario, id_))


@router.post("/paginas/{id_}/restaurar", response_model=PaginaDetalle)
def restaurar(id_: int, sesion: SesionDB, usuario: Editor):
    return _detalle_pagina(sesion, servicio.restaurar(sesion, usuario, id_))


@router.get("/celdas/{id_}/imagen", response_class=Response)
def imagen_celda(id_: int, sesion: SesionDB, _: Editor):
    """Recorte de la celda en el documento original, para compararlo con lo leído."""
    celda = servicio.obtener_celda(sesion, id_)
    if not celda.imagen_png:
        return Response(status_code=404)
    return Response(content=celda.imagen_png, media_type="image/png")
