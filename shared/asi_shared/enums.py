"""Valores fijos del dominio.

Se definen una sola vez aquí para que servidor y cliente usen exactamente
los mismos textos. Los valores (lado derecho) son los que se guardan en la
base de datos y viajan por la API, así que no deben cambiarse una vez en uso.
"""

from datetime import time
from enum import StrEnum


class EstadoAsistencia(StrEnum):
    # "Pendiente" no se guarda: un docente sin registro del día está pendiente.
    # Así el sistema nunca supone asistencia de forma automática.
    PENDIENTE = "pendiente"
    ASISTIO = "asistio"
    FALTO = "falto"
    RETARDO = "retardo"
    JUSTIFICADO = "justificado"


class Turno(StrEnum):
    MATUTINO = "matutino"  # actividades que empiezan antes de las 14:00
    VESPERTINO = "vespertino"  # actividades que empiezan a las 14:00 o después


INICIO_VESPERTINO = time(14, 0)


def turno_de(hora_inicio: time) -> Turno:
    """Turno de una actividad según su hora de inicio (regla de la Jefatura)."""
    return Turno.MATUTINO if hora_inicio < INICIO_VESPERTINO else Turno.VESPERTINO


class TipoEventoCalendario(StrEnum):
    INHABIL = "inhabil"  # día festivo o inhábil
    VACACIONES = "vacaciones"
    SUSPENSION = "suspension"  # suspensión de actividades (p. ej. contingencia)
    HABIL = "habil"  # excepción autorizada: día hábil aunque coincida con los anteriores


class TipoIncidencia(StrEnum):
    COMISION = "comision"
    PERMISO = "permiso"
    SALIDA_ANTICIPADA = "salida_anticipada"
    CAMBIO_AULA = "cambio_aula"
    OTRA = "otra"


class EstadoPeriodo(StrEnum):
    BORRADOR = "borrador"
    ACTIVO = "activo"
    CERRADO = "cerrado"


class EstadoHorario(StrEnum):
    """Ciclo de vida de una versión de horario.

    borrador -> vigente (confirmado por un administrador) -> historico (reemplazado)
    borrador -> descartado
    Solo puede haber una versión vigente por docente y periodo.
    """

    BORRADOR = "borrador"
    VIGENTE = "vigente"
    HISTORICO = "historico"
    DESCARTADO = "descartado"


class OrigenHorario(StrEnum):
    MANUAL = "manual"
    PDF = "pdf"
    EXCEL = "excel"
    CSV = "csv"


class TipoAsignatura(StrEnum):
    MATERIA = "materia"  # clase con grupo, p. ej. "CÁLC. DIF."
    ACTIVIDAD = "actividad"  # gestión, tutoría, residencia, investigación…


class DiaSemana(StrEnum):
    LUNES = "lunes"
    MARTES = "martes"
    MIERCOLES = "miercoles"
    JUEVES = "jueves"
    VIERNES = "viernes"
    SABADO = "sabado"


class Permiso(StrEnum):
    """Permisos individuales. Los roles agrupan permisos en la base de datos."""

    DOCENTES_VER = "docentes.ver"
    DOCENTES_EDITAR = "docentes.editar"
    HORARIOS_VER = "horarios.ver"
    HORARIOS_EDITAR = "horarios.editar"
    HORARIOS_CONFIRMAR = "horarios.confirmar"
    PERIODOS_GESTIONAR = "periodos.gestionar"
    ASISTENCIA_VER = "asistencia.ver"
    ASISTENCIA_REGISTRAR = "asistencia.registrar"
    ASISTENCIA_CORREGIR = "asistencia.corregir"
    DOCUMENTOS_VER = "documentos.ver"
    DOCUMENTOS_GESTIONAR = "documentos.gestionar"
    REPORTES_VER = "reportes.ver"
    REPORTES_GENERAR = "reportes.generar"
    USUARIOS_GESTIONAR = "usuarios.gestionar"
