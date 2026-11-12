"""Datos iniciales de una base nueva: los mismos que dejan las migraciones de PostgreSQL.

Las migraciones ya publicadas no se modifican; este módulo reproduce su resultado final
para bases SQLite. La prueba `test_datos_iniciales_iguales_a_las_migraciones` compara
ambos contra una base PostgreSQL migrada.
"""

from sqlalchemy import insert, select

from app.models import CategoriaDocumento, ConfiguracionAsistencia, Permiso, Rol
from app.models.seguridad import rol_permiso

# Migración fe6d6759717c: permisos iniciales. El rol «consulta» recibe los «.ver» de esta lista.
PERMISOS_INICIALES = [
    ("docentes.ver", "Consultar docentes"),
    ("docentes.editar", "Crear y editar docentes"),
    ("horarios.ver", "Consultar horarios"),
    ("horarios.editar", "Crear, importar y editar horarios"),
    ("periodos.gestionar", "Crear, activar y cerrar periodos"),
    ("asistencia.ver", "Consultar bitácora y asistencia"),
    ("asistencia.registrar", "Registrar y corregir asistencia"),
    ("documentos.ver", "Consultar documentos permitidos"),
    ("documentos.gestionar", "Subir, clasificar y editar documentos"),
    ("reportes.ver", "Consultar reportes autorizados"),
    ("reportes.generar", "Generar y exportar reportes"),
    ("usuarios.gestionar", "Administrar usuarios y permisos"),
]
# Migraciones posteriores: permisos solo para el administrador, en el mismo orden.
PERMISOS_POSTERIORES = [
    ("horarios.confirmar", "Confirmar la versión vigente de un horario"),
    ("asistencia.corregir", "Corregir asistencias de días anteriores y en días inhábiles"),
    ("documentos.descargar", "Descargar originales del archivo privado"),
]
ROLES = [
    ("administrador", "Gestión completa del sistema"),
    ("consulta", "Solo consulta de información"),
]
CATEGORIAS = [
    ("horario", "Horario original", False),
    ("justificante", "Justificante", True),
    ("permiso", "Permiso", True),
    ("comision", "Comisión", True),
    ("otro", "Otro documento", False),
]
TOLERANCIA_INICIAL = 10


def cargar_datos_iniciales(conexion) -> None:
    for clave, descripcion in PERMISOS_INICIALES + PERMISOS_POSTERIORES:
        conexion.execute(insert(Permiso).values(clave=clave, descripcion=descripcion))
    for nombre, descripcion in ROLES:
        conexion.execute(insert(Rol).values(nombre=nombre, descripcion=descripcion))
    permisos = dict(conexion.execute(select(Permiso.clave, Permiso.id)).all())
    roles = dict(conexion.execute(select(Rol.nombre, Rol.id)).all())
    for id_permiso in permisos.values():
        conexion.execute(
            insert(rol_permiso).values(rol_id=roles["administrador"], permiso_id=id_permiso)
        )
    for clave, _ in PERMISOS_INICIALES:
        if clave.endswith(".ver"):
            conexion.execute(
                insert(rol_permiso).values(rol_id=roles["consulta"], permiso_id=permisos[clave])
            )
    for clave, nombre, justificantes in CATEGORIAS:
        conexion.execute(
            insert(CategoriaDocumento).values(
                clave=clave, nombre=nombre, admite_justificantes=justificantes
            )
        )
    conexion.execute(
        insert(ConfiguracionAsistencia).values(id=1, tolerancia_minutos=TOLERANCIA_INICIAL)
    )
