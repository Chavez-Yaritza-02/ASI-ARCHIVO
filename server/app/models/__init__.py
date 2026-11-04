"""Importa todos los modelos para que Alembic los detecte."""

from app.models.asistencia import Asistencia, EventoCalendario, Incidencia
from app.models.auditoria import Auditoria
from app.models.base import Base
from app.models.catalogos import Asignatura, Aula, Docente, Grupo
from app.models.configuracion import ConfiguracionAsistencia
from app.models.horarios import BloqueHorario, Horario, Periodo
from app.models.importacion import (
    CeldaImportada,
    DocumentoImportado,
    Importacion,
    PaginaImportada,
)
from app.models.seguridad import Permiso, Rol, Usuario

__all__ = [
    "Asignatura",
    "Asistencia",
    "Auditoria",
    "Aula",
    "Base",
    "BloqueHorario",
    "CeldaImportada",
    "Docente",
    "ConfiguracionAsistencia",
    "DocumentoImportado",
    "EventoCalendario",
    "Grupo",
    "Horario",
    "Importacion",
    "Incidencia",
    "PaginaImportada",
    "Periodo",
    "Permiso",
    "Rol",
    "Usuario",
]
