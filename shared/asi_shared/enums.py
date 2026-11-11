"""Valores fijos del dominio.

Se definen una sola vez aquí para que servidor y cliente usen exactamente
los mismos textos. Los valores (lado derecho) son los que se guardan en la
base de datos y viajan por la API, así que no deben cambiarse una vez en uso.
"""

from enum import StrEnum


class EstadoAsistencia(StrEnum):
    # "Pendiente" no se guarda: un docente sin registro del día está pendiente.
    # Así el sistema nunca supone asistencia de forma automática.
    PENDIENTE = "pendiente"
    ASISTIO = "asistio"
    FALTO = "falto"
    RETARDO = "retardo"
    JUSTIFICADO = "justificado"


class EstadoPeriodo(StrEnum):
    BORRADOR = "borrador"
    ACTIVO = "activo"
    CERRADO = "cerrado"


class Permiso(StrEnum):
    """Permisos individuales. Los roles agrupan permisos en la base de datos."""

    DOCENTES_VER = "docentes.ver"
    DOCENTES_EDITAR = "docentes.editar"
    HORARIOS_VER = "horarios.ver"
    HORARIOS_EDITAR = "horarios.editar"
    PERIODOS_GESTIONAR = "periodos.gestionar"
    ASISTENCIA_VER = "asistencia.ver"
    ASISTENCIA_REGISTRAR = "asistencia.registrar"
    DOCUMENTOS_VER = "documentos.ver"
    DOCUMENTOS_GESTIONAR = "documentos.gestionar"
    REPORTES_VER = "reportes.ver"
    REPORTES_GENERAR = "reportes.generar"
    USUARIOS_GESTIONAR = "usuarios.gestionar"
