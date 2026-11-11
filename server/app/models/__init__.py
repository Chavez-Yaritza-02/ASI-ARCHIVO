"""Importa todos los modelos para que Alembic los detecte."""

from app.models.auditoria import Auditoria
from app.models.base import Base
from app.models.catalogos import Asignatura, Aula, Docente, Grupo
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
    "Auditoria",
    "Aula",
    "Base",
    "BloqueHorario",
    "CeldaImportada",
    "Docente",
    "DocumentoImportado",
    "Grupo",
    "Horario",
    "Importacion",
    "PaginaImportada",
    "Periodo",
    "Permiso",
    "Rol",
    "Usuario",
]
