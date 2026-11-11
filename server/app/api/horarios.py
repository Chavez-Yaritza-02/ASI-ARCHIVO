"""Endpoints de horarios versionados."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import SesionDB, requiere_permiso
from app.models import Usuario
from app.schemas.horarios import (
    ORDEN_DIAS,
    BloqueEntrada,
    Confirmacion,
    HorarioCrear,
    HorarioDetalle,
    HorarioEditar,
    HorarioResumen,
    detalle,
    resumen,
)
from app.services import horarios as servicio
from asi_shared import EstadoHorario, Permiso

router = APIRouter(prefix="/horarios", tags=["horarios"])
Lector = Annotated[Usuario, Depends(requiere_permiso(Permiso.HORARIOS_VER))]
Editor = Annotated[Usuario, Depends(requiere_permiso(Permiso.HORARIOS_EDITAR))]
Confirmador = Annotated[Usuario, Depends(requiere_permiso(Permiso.HORARIOS_CONFIRMAR))]


@router.get("", response_model=list[HorarioResumen])
def listar(
    sesion: SesionDB,
    _: Lector,
    docente_id: int | None = None,
    periodo_id: int | None = None,
    estado: EstadoHorario | None = None,
):
    return [resumen(h) for h in servicio.listar(sesion, docente_id, periodo_id, estado)]


@router.get("/{id_}", response_model=HorarioDetalle)
def consultar(id_: int, sesion: SesionDB, _: Lector):
    horario = servicio.obtener(sesion, id_)
    avisos = servicio.advertencias(sesion, horario) if horario.estado == "borrador" else []
    return detalle(horario, avisos)


@router.post("", response_model=HorarioDetalle, status_code=201)
def crear(datos: HorarioCrear, sesion: SesionDB, usuario: Editor):
    horario = servicio.crear_borrador(
        sesion,
        usuario,
        datos.docente_id,
        datos.periodo_id,
        datos.basado_en_id,
        datos.origen,
        datos.notas,
    )
    return detalle(horario)


@router.patch("/{id_}", response_model=HorarioDetalle)
def editar(id_: int, datos: HorarioEditar, sesion: SesionDB, usuario: Editor):
    return detalle(servicio.editar_datos(sesion, usuario, id_, datos.notas))


@router.put("/{id_}/bloques", response_model=HorarioDetalle)
def reemplazar_bloques(id_: int, bloques: list[BloqueEntrada], sesion: SesionDB, usuario: Editor):
    """Sustituye todos los bloques del borrador. Valida traslapes antes de guardar."""
    entradas = [
        servicio.BloqueEntrada(
            dia=ORDEN_DIAS.index(b.dia),
            hora_inicio=b.hora_inicio,
            hora_fin=b.hora_fin,
            asignatura_id=b.asignatura_id,
            grupo_id=b.grupo_id,
            aula_id=b.aula_id,
            grupo_letra=(b.grupo_letra or "").strip().upper() or None,
        )
        for b in bloques
    ]
    horario = servicio.reemplazar_bloques(sesion, usuario, id_, entradas)
    return detalle(horario, servicio.advertencias(sesion, horario))


@router.post("/{id_}/confirmar", response_model=HorarioDetalle)
def confirmar(id_: int, datos: Confirmacion, sesion: SesionDB, usuario: Confirmador):
    """Convierte el borrador en la versión vigente. Si hay advertencias (aula ocupada,
    versión idéntica) responde 409 con la lista, salvo que se acepten explícitamente."""
    return detalle(
        servicio.confirmar(sesion, usuario, id_, datos.aceptar_advertencias, datos.vigente_desde)
    )


@router.post("/{id_}/descartar", response_model=HorarioDetalle)
def descartar(id_: int, sesion: SesionDB, usuario: Editor):
    return detalle(servicio.descartar(sesion, usuario, id_))
