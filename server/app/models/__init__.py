"""Importa todos los modelos para que Alembic los detecte."""

from app.models.asistencia import Asistencia, EventoCalendario, Incidencia
from app.models.asistencia_hora import AsistenciaHora
from app.models.auditoria import Auditoria
from app.models.base import Base
from app.models.catalogos import Asignatura, Aula, Docente, Grupo
from app.models.configuracion import ConfiguracionAsistencia
from app.models.documentos import (
    CategoriaDocumento,
    Documento,
    DocumentoAsistencia,
    VersionDocumento,
)
from app.models.horarios import BloqueHorario, Horario, Periodo
from app.models.importacion import (
    CeldaImportada,
    DocumentoImportado,
    Importacion,
    PaginaImportada,
)
from app.models.incidencias_excel import ImportacionIncidencias, IncidenciaImportada
from app.models.seguridad import Permiso, Rol, Usuario

__all__ = [
    "Asignatura",
    "Asistencia",
    "AsistenciaHora",
    "Auditoria",
    "Aula",
    "Base",
    "BloqueHorario",
    "CeldaImportada",
    "Docente",
    "CategoriaDocumento",
    "Documento",
    "VersionDocumento",
    "DocumentoAsistencia",
    "ConfiguracionAsistencia",
    "DocumentoImportado",
    "EventoCalendario",
    "Grupo",
    "Horario",
    "Importacion",
    "ImportacionIncidencias",
    "IncidenciaImportada",
    "Incidencia",
    "PaginaImportada",
    "Periodo",
    "Permiso",
    "Rol",
    "Usuario",
]
