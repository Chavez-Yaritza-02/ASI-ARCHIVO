"""Importa todos los modelos para que Alembic los detecte."""

from app.models.auditoria import Auditoria
from app.models.base import Base
from app.models.seguridad import Permiso, Rol, Usuario

__all__ = ["Auditoria", "Base", "Permiso", "Rol", "Usuario"]
