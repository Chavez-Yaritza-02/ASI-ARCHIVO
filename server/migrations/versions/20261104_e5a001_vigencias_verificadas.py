"""Vigencias verificadas y configuración; no deducir fechas heredadas.

Revision ID: e5a001
Revises: 8b4cb2f4fef8
"""

import sqlalchemy as sa
from alembic import op

revision = "e5a001"
down_revision = "8b4cb2f4fef8"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "horario",
        sa.Column("vigencia_confirmada", sa.Boolean(), server_default="false", nullable=False),
    )
    # La Etapa 4 no distinguía fechas elegidas de fechas inferidas. No es posible
    # certificarlas automáticamente. Guardamos cada valor anterior en auditoría.
    op.execute("""
        INSERT INTO auditoria (accion, entidad, entidad_id, antes, despues)
        SELECT 'vigencia_desconocida', 'horario', id::text,
               jsonb_build_object('vigente_desde', vigente_desde, 'vigente_hasta', vigente_hasta),
               jsonb_build_object('vigente_desde', NULL, 'vigente_hasta', NULL,
                   'motivo', 'Migración e5a001: fechas heredadas sin certeza de confirmación')
        FROM horario WHERE vigente_desde IS NOT NULL OR vigente_hasta IS NOT NULL
    """)
    op.execute("UPDATE horario SET vigente_desde = NULL, vigente_hasta = NULL")
    op.create_check_constraint(
        "ck_horario_vigencia_fechas",
        "horario",
        "(vigente_hasta IS NULL OR (vigente_desde IS NOT NULL AND vigente_hasta >= vigente_desde)) "
        "AND (NOT vigencia_confirmada OR vigente_desde IS NOT NULL)",
    )
    op.create_table(
        "configuracion_asistencia",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tolerancia_minutos", sa.Integer(), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_configuracion_asistencia_unica"),
        sa.CheckConstraint(
            "tolerancia_minutos BETWEEN 0 AND 120", name="ck_configuracion_asistencia_tolerancia"
        ),
    )
    op.execute("INSERT INTO configuracion_asistencia VALUES (1, 10)")


def downgrade():
    # Volver atrás perdería la distinción entre desconocido y confirmado.
    raise RuntimeError("Migración de integridad irreversible: no se restauran fechas inferidas")
