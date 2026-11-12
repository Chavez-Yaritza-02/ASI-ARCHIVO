"""Tablas que solo existen en la base local (SQLite).

Van en sus propios metadatos, fuera de `Base.metadata`: así el esquema de PostgreSQL y sus
migraciones de Alembic no cambian.
"""

from sqlalchemy import Column, Integer, MetaData, String, Table

from app.db.tipos import FechaHora, ahora_bd

METADATOS_LOCALES = MetaData()

# Huella (Argon2) del código de recuperación de la cuenta. Nunca se guarda el código.
cuenta_recuperacion = Table(
    "cuenta_recuperacion",
    METADATOS_LOCALES,
    Column("usuario_id", Integer, primary_key=True),
    Column("huella", String(255), nullable=False),
    Column("creado_en", FechaHora(), nullable=False, server_default=ahora_bd()),
)
