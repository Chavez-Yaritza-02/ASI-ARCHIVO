"""Archivo digital privado: carga, consulta, versiones, descarga y justificantes."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from app.api.deps import SesionDB, requiere_permiso
from app.archivos import almacen
from app.core.config import obtener_configuracion
from app.models import CategoriaDocumento, Usuario
from app.services import documentos as servicio
from app.services.comun import auditar

router = APIRouter(prefix="/documentos", tags=["archivo digital"])
Lector = Annotated[Usuario, Depends(requiere_permiso("documentos.ver"))]
Gestor = Annotated[Usuario, Depends(requiere_permiso("documentos.gestionar"))]
Descargador = Annotated[Usuario, Depends(requiere_permiso("documentos.descargar"))]
Registrador = Annotated[Usuario, Depends(requiere_permiso("asistencia.registrar"))]


class DatosDocumento(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    nombre: str = Field(min_length=1, max_length=200)
    descripcion: str = Field("", max_length=2000)
    fecha: date
    categoria_id: int = Field(ge=1)
    docente_id: int | None = Field(None, ge=1)
    periodo_id: int | None = Field(None, ge=1)


class Motivo(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    motivo: str = Field(min_length=5, max_length=1000)


class Edicion(Motivo):
    nombre: str | None = Field(None, min_length=1, max_length=200)
    descripcion: str | None = Field(None, max_length=2000)
    fecha: date | None = None
    categoria_id: int | None = Field(None, ge=1)
    docente_id: int | None = Field(None, ge=1)
    periodo_id: int | None = Field(None, ge=1)


class VinculoEntrada(Motivo):
    version_id: int = Field(ge=1)
    asistencia_id: int = Field(ge=1)


class CategoriaEntrada(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    clave: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,39}$")
    nombre: str = Field(min_length=1, max_length=100)
    admite_justificantes: bool = False


@router.get("/estado")
def estado(_: Lector):
    c = obtener_configuracion()
    return {
        "limite_mb": c.archivo_max_mb,
        "formatos": ["PDF", "PNG", "JPEG"],
        "cargas_habilitadas": bool(c.archivo_antivirus_cmd)
        or (not c.archivo_requerir_antivirus and c.entorno in ("pruebas", "desarrollo")),
        "antivirus_requerido": c.archivo_requerir_antivirus
        or c.entorno not in ("pruebas", "desarrollo"),
    }


@router.get("/categorias")
def categorias(sesion: SesionDB, _: Lector):
    return [
        {
            "id": c.id,
            "clave": c.clave,
            "nombre": c.nombre,
            "admite_justificantes": c.admite_justificantes,
        }
        for c in sesion.scalars(select(CategoriaDocumento).order_by(CategoriaDocumento.nombre))
    ]


@router.post("/categorias", status_code=201)
def crear_categoria(datos: CategoriaEntrada, sesion: SesionDB, usuario: Gestor):
    c = CategoriaDocumento(**datos.model_dump())
    sesion.add(c)
    sesion.flush()
    auditar(sesion, usuario, "crear", "categoria_documento", c.id, despues=datos.model_dump())
    sesion.commit()
    return {"id": c.id, **datos.model_dump()}


async def leer_archivo(archivo):
    try:
        almacen.nombre_seguro(archivo.filename)
        limite = obtener_configuracion().archivo_max_mb * 1024 * 1024
        contenido = bytearray()
        while bloque := await archivo.read(min(1024 * 1024, limite + 1 - len(contenido))):
            contenido.extend(bloque)
            if len(contenido) > limite:
                raise HTTPException(413, "El archivo excede el tamaño permitido")
        return bytes(contenido)
    finally:
        await archivo.close()


@router.post("", status_code=201)
async def crear(
    sesion: SesionDB,
    usuario: Gestor,
    archivo: Annotated[UploadFile, File()],
    datos: Annotated[str, Form()],
):
    try:
        metadatos = DatosDocumento.model_validate_json(datos)
    except ValidationError as error:
        await archivo.close()
        raise HTTPException(422, "Metadatos del documento inválidos") from error
    nombre, mime = archivo.filename, archivo.content_type
    contenido = await leer_archivo(archivo)
    return await run_in_threadpool(
        servicio.crear, sesion, usuario, metadatos.model_dump(), contenido, nombre, mime
    )


@router.get("")
def listar(
    sesion: SesionDB,
    usuario: Lector,
    texto: str = Query("", max_length=200),
    docente_id: int | None = Query(None, ge=1),
    periodo_id: int | None = Query(None, ge=1),
    categoria_id: int | None = Query(None, ge=1),
    desde: date | None = None,
    hasta: date | None = None,
    incluir_archivados: bool = False,
    offset: int = Query(0, ge=0),
    limite: int = Query(50, ge=1, le=100),
    docente_nombre: str = Query("", max_length=150),
    asistencia_id: int | None = Query(None, ge=1),
):
    if asistencia_id is not None and "asistencia.ver" not in usuario.permisos:
        raise HTTPException(403, "Consultar vínculos requiere asistencia.ver")
    return servicio.listar(
        sesion,
        usuario,
        texto,
        docente_id,
        periodo_id,
        categoria_id,
        desde,
        hasta,
        incluir_archivados,
        offset,
        limite,
        docente_nombre=docente_nombre,
        asistencia_id=asistencia_id,
    )


@router.get("/{id_}")
def detalle(id_: int, sesion: SesionDB, usuario: Lector):
    return servicio.detalle(sesion, usuario, id_)


@router.patch("/{id_}")
def editar(id_: int, datos: Edicion, sesion: SesionDB, usuario: Gestor):
    cambios = datos.model_dump(exclude_unset=True, exclude={"motivo"})
    for campo in ("nombre", "descripcion", "fecha", "categoria_id"):
        if campo in cambios and cambios[campo] is None:
            raise HTTPException(422, "Este campo no admite un valor vacío")
    return servicio.editar(sesion, usuario, id_, cambios, datos.motivo)


@router.post("/{id_}/versiones", status_code=201)
async def nueva_version(
    id_: int,
    sesion: SesionDB,
    usuario: Gestor,
    archivo: Annotated[UploadFile, File()],
    motivo: Annotated[str, Form(min_length=5, max_length=1000)],
):
    nombre, mime = archivo.filename, archivo.content_type
    contenido = await leer_archivo(archivo)
    return await run_in_threadpool(
        servicio.subir_version, sesion, usuario, id_, contenido, nombre, mime, motivo
    )


@router.post("/{id_}/archivar")
def archivar(id_: int, datos: Motivo, sesion: SesionDB, usuario: Gestor):
    return servicio.archivar(sesion, usuario, id_, False, datos.motivo)


@router.post("/{id_}/restaurar")
def restaurar(id_: int, datos: Motivo, sesion: SesionDB, usuario: Gestor):
    return servicio.archivar(sesion, usuario, id_, True, datos.motivo)


@router.get("/{id_}/versiones/{version_id}/vista")
def vista(
    id_: int, version_id: int, sesion: SesionDB, usuario: Lector, pagina: int = Query(1, ge=1)
):
    datos, _ = servicio.contenido(sesion, usuario, id_, version_id, pagina)
    return Response(
        datos,
        media_type="image/png",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.get("/{id_}/versiones/{version_id}/descargar")
def descargar(id_: int, version_id: int, sesion: SesionDB, usuario: Descargador, _: Lector):
    datos, v = servicio.contenido(sesion, usuario, id_, version_id)
    extension = {"application/pdf": "pdf", "image/png": "png", "image/jpeg": "jpg"}[v.mime]
    return Response(
        datos,
        media_type=v.mime,
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": (
                f'attachment; filename="documento_{id_}_v{v.numero}.{extension}"'
            ),
        },
    )


@router.post("/{id_}/vinculos", status_code=201)
def vincular(id_: int, datos: VinculoEntrada, sesion: SesionDB, usuario: Gestor, _: Registrador):
    return servicio.vincular(
        sesion, usuario, id_, datos.version_id, datos.asistencia_id, datos.motivo
    )


@router.post("/{id_}/vinculos/{enlace_id}/anular")
def desvincular(
    id_: int, enlace_id: int, datos: Motivo, sesion: SesionDB, usuario: Gestor, _: Registrador
):
    return servicio.desvincular(sesion, usuario, id_, enlace_id, datos.motivo)


@router.get("/{id_}/historial")
def historial(id_: int, sesion: SesionDB, usuario: Lector):
    return servicio.historial(sesion, usuario, id_)
