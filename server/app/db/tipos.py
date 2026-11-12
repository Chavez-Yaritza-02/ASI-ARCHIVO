"""Tipos y expresiones que funcionan igual en PostgreSQL y en SQLite.

En PostgreSQL generan exactamente el mismo esquema que antes (la comparación con las
migraciones lo comprueba). En SQLite adaptan lo que esa base no tiene:

- JSON: `JSONB` en PostgreSQL, `JSON` en SQLite.
- FechaHora: SQLite no guarda la zona horaria; se guarda en UTC y se devuelve con zona,
  para que las comparaciones y la auditoría den lo mismo que en PostgreSQL.
- segundos_entre(): duración entre dos horas para las reglas (CHECK) de las tablas.
- ahora_bd(): hora actual de la base. En PostgreSQL `now()`; en SQLite con milisegundos
  (CURRENT_TIMESTAMP solo llega al segundo y el sello de las sesiones depende de ella).
"""

from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.expression import ColumnElement, FunctionElement
from sqlalchemy.types import Integer, TypeDecorator

JSONCompatible = JSON().with_variant(JSONB(), "postgresql")


class FechaHora(TypeDecorator):
    """Fecha y hora con zona horaria en ambas bases (en SQLite, UTC)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, valor, dialect):
        if valor is None or dialect.name != "sqlite":
            return valor
        # Sin zona: se toma como hora local de la computadora (como PostgreSQL con su zona).
        return valor.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, valor, dialect):
        if valor is None or dialect.name != "sqlite":
            return valor
        if isinstance(valor, str):  # CURRENT_TIMESTAMP de SQLite
            valor = datetime.fromisoformat(valor)
        return valor.replace(tzinfo=UTC) if valor.tzinfo is None else valor


class segundos_entre(ColumnElement):  # noqa: N801 (se usa como función SQL)
    """Segundos de `inicio` a `fin` (columnas de tipo hora), para reglas CHECK."""

    type = Integer()
    inherit_cache = True

    def __init__(self, fin: str, inicio: str):
        self.fin, self.inicio = fin, inicio


@compiles(segundos_entre, "postgresql")
def _segundos_pg(elemento, _compilador, **_kw):
    return f"EXTRACT(EPOCH FROM ({elemento.fin}-{elemento.inicio}))"


@compiles(segundos_entre, "sqlite")
def _segundos_sqlite(elemento, _compilador, **_kw):
    return f"(strftime('%s', {elemento.fin}) - strftime('%s', {elemento.inicio}))"


class ahora_bd(FunctionElement):  # noqa: N801 (se usa como función SQL)
    type = DateTime(timezone=True)
    inherit_cache = True


@compiles(ahora_bd)
def _ahora_generico(_elemento, _compilador, **_kw):
    return "now()"


@compiles(ahora_bd, "sqlite")
def _ahora_sqlite(_elemento, _compilador, **_kw):
    # Seis dígitos de fracción, como espera el tipo de fecha de SQLAlchemy.
    return "(strftime('%Y-%m-%d %H:%M:%f', 'now') || '000')"
