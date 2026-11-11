"""Configuración de Alembic: usa la misma conexión y modelos que la API."""

from logging.config import fileConfig

from alembic import context

from app.db.proteccion_pruebas import en_pruebas, validar_conexion_pruebas
from app.db.sesion import obtener_engine
from app.models import Base

if context.config.config_file_name is not None:
    fileConfig(context.config.config_file_name)


def ejecutar_migraciones() -> None:
    conexion_externa = context.config.attributes.get("connection")
    if conexion_externa is not None:  # usado por las pruebas
        if en_pruebas():
            validar_conexion_pruebas(conexion_externa)
        context.configure(connection=conexion_externa, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()
        return

    with obtener_engine().connect() as conexion:
        if en_pruebas():
            validar_conexion_pruebas(conexion)
            conexion.commit()
        context.configure(connection=conexion, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()


ejecutar_migraciones()
