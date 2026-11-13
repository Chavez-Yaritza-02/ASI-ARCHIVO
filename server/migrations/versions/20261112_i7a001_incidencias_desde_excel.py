"""incidencias desde excel

Solo agrega dos tablas nuevas (zona de revisión de incidencias importadas). No modifica
ni mueve ningún registro existente.

Revision ID: i7a001
Revises: e6a001
Create Date: 2026-11-12 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "i7a001"
down_revision: str | None = "e6a001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _fechas() -> list[sa.Column]:
    return [
        sa.Column(
            "creado_en", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "actualizado_en",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "importacion_incidencias",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("nombre_archivo", sa.String(length=255), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("hoja", sa.String(length=100), nullable=False),
        sa.Column("usuario_id", sa.Integer(), nullable=True),
        sa.Column("total_filas", sa.Integer(), nullable=False),
        *_fechas(),
        sa.ForeignKeyConstraint(
            ["usuario_id"],
            ["usuario.id"],
            name=op.f("fk_importacion_incidencias_usuario_id_usuario"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_importacion_incidencias")),
        sa.UniqueConstraint("sha256", name=op.f("uq_importacion_incidencias_sha256")),
    )
    op.create_table(
        "incidencia_importada",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("importacion_id", sa.Integer(), nullable=False),
        sa.Column("fila", sa.Integer(), nullable=False),
        sa.Column("fecha_texto", sa.String(length=60), nullable=False),
        sa.Column("docente_texto", sa.String(length=200), nullable=False),
        sa.Column("tipo_texto", sa.String(length=200), nullable=False),
        sa.Column("detalle_texto", sa.Text(), nullable=False),
        sa.Column("fecha", sa.Date(), nullable=True),
        sa.Column("docente_id", sa.Integer(), nullable=True),
        sa.Column("docente_estado", sa.String(length=20), nullable=False),
        sa.Column("tipo", sa.String(length=20), nullable=True),
        sa.Column("hora_salida", sa.Time(), nullable=True),
        sa.Column("horas", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("justificada", sa.Boolean(), nullable=False),
        sa.Column("motivo", sa.Text(), nullable=False),
        sa.Column("observaciones", sa.Text(), nullable=False),
        sa.Column("documento_id", sa.Integer(), nullable=True),
        sa.Column("estado", sa.String(length=20), nullable=False),
        sa.Column("asistencias", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("importada_por_id", sa.Integer(), nullable=True),
        sa.Column("importada_en", sa.DateTime(timezone=True), nullable=True),
        *_fechas(),
        sa.CheckConstraint(
            "estado IN ('pendiente', 'importada', 'descartada')",
            name=op.f("ck_incidencia_importada_estado"),
        ),
        sa.CheckConstraint(
            "tipo IS NULL OR tipo IN ('falta', 'salida_anticipada')",
            name=op.f("ck_incidencia_importada_tipo"),
        ),
        sa.CheckConstraint(
            "docente_estado IN ('coincide', 'sugerido', 'sin_coincidencia', 'confirmado')",
            name=op.f("ck_incidencia_importada_docente_estado"),
        ),
        sa.ForeignKeyConstraint(
            ["docente_id"], ["docente.id"], name=op.f("fk_incidencia_importada_docente_id_docente")
        ),
        sa.ForeignKeyConstraint(
            ["documento_id"],
            ["documento.id"],
            name=op.f("fk_incidencia_importada_documento_id_documento"),
        ),
        sa.ForeignKeyConstraint(
            ["importacion_id"],
            ["importacion_incidencias.id"],
            name=op.f("fk_incidencia_importada_importacion_id_importacion_incidencias"),
        ),
        sa.ForeignKeyConstraint(
            ["importada_por_id"],
            ["usuario.id"],
            name=op.f("fk_incidencia_importada_importada_por_id_usuario"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_incidencia_importada")),
        sa.UniqueConstraint("importacion_id", "fila", name="uq_incidencia_importada_fila"),
    )
    op.create_index(
        op.f("ix_incidencia_importada_docente_id"), "incidencia_importada", ["docente_id"]
    )
    op.create_index(op.f("ix_incidencia_importada_fecha"), "incidencia_importada", ["fecha"])
    op.create_index(
        op.f("ix_incidencia_importada_importacion_id"), "incidencia_importada", ["importacion_id"]
    )


def downgrade() -> None:
    raise RuntimeError("No se eliminan incidencias importadas mediante downgrade")
