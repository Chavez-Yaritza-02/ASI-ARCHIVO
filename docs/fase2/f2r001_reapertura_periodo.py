"""BORRADOR — reapertura excepcional de periodos (fase 2). NO EJECUTAR.

Este archivo está a propósito FUERA de server/migrations/versions/: Alembic no lo ve y
ninguna instalación lo aplica. Para usarlo, cuando se autorice, se copia a
server/migrations/versions/ y se prueba primero solo en la base de pruebas.

Cambio 100 % aditivo:
- Crea la tabla `reapertura_periodo`. No modifica columnas, estados ni datos existentes.
- No toca `periodo` (sus estados siguen siendo borrador | activo | cerrado y el índice
  de «un solo periodo activo» se conserva).
- Impide borrar o reescribir reaperturas (solo se puede registrar su cierre una vez).

Revision ID: f2r001
Revises: e6a001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f2r001"
down_revision: str | None = "e6a001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reapertura_periodo",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("periodo_id", sa.Integer(), nullable=False),
        sa.Column("motivo", sa.Text(), nullable=False),
        sa.Column("abierta_por_id", sa.Integer(), nullable=False),
        sa.Column(
            "abierta_en",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("vence_en", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cerrada_por_id", sa.Integer(), nullable=True),
        sa.Column("cerrada_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("motivo_cierre", sa.Text(), nullable=True),
        sa.CheckConstraint("char_length(motivo) >= 15", name=op.f("ck_reapertura_periodo_motivo")),
        sa.CheckConstraint(
            "vence_en > abierta_en AND vence_en <= abierta_en + interval '30 days'",
            name=op.f("ck_reapertura_periodo_plazo"),
        ),
        sa.CheckConstraint(
            "(cerrada_en IS NULL) = (cerrada_por_id IS NULL)",
            name=op.f("ck_reapertura_periodo_cierre"),
        ),
        sa.ForeignKeyConstraint(
            ["periodo_id"], ["periodo.id"], name=op.f("fk_reapertura_periodo_periodo_id_periodo")
        ),
        sa.ForeignKeyConstraint(
            ["abierta_por_id"],
            ["usuario.id"],
            name=op.f("fk_reapertura_periodo_abierta_por_id_usuario"),
        ),
        sa.ForeignKeyConstraint(
            ["cerrada_por_id"],
            ["usuario.id"],
            name=op.f("fk_reapertura_periodo_cerrada_por_id_usuario"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reapertura_periodo")),
    )
    op.create_index(op.f("ix_reapertura_periodo_periodo_id"), "reapertura_periodo", ["periodo_id"])
    # Como máximo una reapertura sin cerrar por periodo (las vencidas se cierran al consultarlas).
    op.create_index(
        "uq_reapertura_periodo_abierta",
        "reapertura_periodo",
        ["periodo_id"],
        unique=True,
        postgresql_where=sa.text("cerrada_en IS NULL"),
    )
    # Historial inmutable: no se borra; solo se permite registrar el cierre una sola vez.
    op.execute(
        """
        CREATE FUNCTION reapertura_inmutable() RETURNS trigger AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'Las reaperturas de periodo no se borran';
          END IF;
          IF OLD.cerrada_en IS NOT NULL
             OR NEW.id <> OLD.id OR NEW.periodo_id <> OLD.periodo_id
             OR NEW.motivo <> OLD.motivo OR NEW.abierta_por_id <> OLD.abierta_por_id
             OR NEW.abierta_en <> OLD.abierta_en OR NEW.vence_en <> OLD.vence_en THEN
            RAISE EXCEPTION 'Una reapertura solo admite registrar su cierre, una vez';
          END IF;
          RETURN NEW;
        END $$ LANGUAGE plpgsql;
        CREATE TRIGGER trg_reapertura_inmutable BEFORE UPDATE OR DELETE ON reapertura_periodo
            FOR EACH ROW EXECUTE FUNCTION reapertura_inmutable();
        """
    )


def downgrade() -> None:
    # Solo para la base de pruebas. En producción NO se revierte: se perdería el historial.
    op.execute("DROP TRIGGER IF EXISTS trg_reapertura_inmutable ON reapertura_periodo")
    op.execute("DROP FUNCTION IF EXISTS reapertura_inmutable()")
    op.drop_index("uq_reapertura_periodo_abierta", table_name="reapertura_periodo")
    op.drop_index(op.f("ix_reapertura_periodo_periodo_id"), table_name="reapertura_periodo")
    op.drop_table("reapertura_periodo")
