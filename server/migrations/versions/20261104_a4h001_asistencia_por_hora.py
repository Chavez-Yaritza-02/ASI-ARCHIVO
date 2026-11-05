"""Asistencia por hora: tabla nueva, sin convertir ni modificar registros previos.

Revision ID: a4h001
Revises: e5a001
"""

import sqlalchemy as sa
from alembic import op

revision = "a4h001"
down_revision = "e5a001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "asistencia_hora",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("docente_id", sa.Integer(), sa.ForeignKey("docente.id"), nullable=False),
        sa.Column("fecha", sa.Date(), nullable=False),
        sa.Column("periodo_id", sa.Integer(), sa.ForeignKey("periodo.id"), nullable=False),
        sa.Column("horario_id", sa.Integer(), sa.ForeignKey("horario.id"), nullable=False),
        sa.Column("bloque_id", sa.Integer(), sa.ForeignKey("bloque_horario.id"), nullable=False),
        sa.Column("docente_nombre", sa.String(150), nullable=False),
        sa.Column("asignatura", sa.String(120), nullable=False),
        sa.Column("tipo_actividad", sa.String(20), nullable=False),
        sa.Column("grupo", sa.String(80)),
        sa.Column("aula", sa.String(30)),
        sa.Column("turno", sa.String(12), nullable=False),
        sa.Column("programado_inicio", sa.Time(), nullable=False),
        sa.Column("programado_fin", sa.Time(), nullable=False),
        sa.Column("estado", sa.String(15), nullable=False),
        sa.Column("hora_entrada", sa.Time()),
        sa.Column("hora_salida", sa.Time()),
        sa.Column("minutos_cumplidos", sa.Integer(), nullable=False),
        sa.Column("minutos_justificados", sa.Integer(), nullable=False),
        sa.Column("observaciones", sa.Text(), nullable=False),
        sa.Column("justificacion", sa.Text(), nullable=False),
        sa.Column("en_dia_inhabil", sa.Boolean(), nullable=False),
        sa.Column("registrado_por_id", sa.Integer(), sa.ForeignKey("usuario.id")),
        sa.Column("correcciones", sa.Integer(), nullable=False),
        sa.Column(
            "creado_en", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "actualizado_en",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "docente_id",
            "fecha",
            "programado_inicio",
            name="uq_asistencia_hora_docente_fecha_inicio",
        ),
        sa.CheckConstraint(
            "estado IN ('asistio','retardo','falto','justificado','parcial')", name="estado"
        ),
        sa.CheckConstraint("turno IN ('matutino','vespertino')", name="turno"),
        sa.CheckConstraint(
            "programado_fin > programado_inicio AND "
            "EXTRACT(EPOCH FROM (programado_fin-programado_inicio)) <= 3600",
            name="tramo",
        ),
        sa.CheckConstraint(
            "minutos_cumplidos >= 0 AND minutos_justificados >= 0 AND "
            "(minutos_cumplidos + minutos_justificados) * 60 <= "
            "EXTRACT(EPOCH FROM (programado_fin-programado_inicio))",
            name="minutos",
        ),
        sa.CheckConstraint(
            "hora_salida IS NULL OR hora_entrada IS NULL OR hora_salida > hora_entrada",
            name="horas",
        ),
    )
    op.create_index("ix_asistencia_hora_docente_id", "asistencia_hora", ["docente_id"])
    op.create_index("ix_asistencia_hora_fecha", "asistencia_hora", ["fecha"])


def downgrade():
    raise RuntimeError("No se elimina la asistencia horaria ni su historial mediante downgrade")
