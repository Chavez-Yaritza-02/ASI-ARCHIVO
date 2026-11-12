"""Zona de revisión de la importación de horarios desde PDF.

Nada de lo que hay aquí es un horario oficial. Cada página leída queda "por revisar":
el usuario corrige docente, asignaturas, grupos, aulas, días y horas, y al aprobarla
se crea un horario en *borrador*. Volverlo vigente sigue siendo una confirmación
aparte (permiso horarios.confirmar).

Estados de comparación con los catálogos (campo *_estado):
- coincide: el texto leído es idéntico a un registro del catálogo.
- sugerido: se parece a un único registro; el usuario debe aceptarlo.
- sin_coincidencia: no se parece a nada, o a varios registros (ambiguo).
- confirmado: el usuario eligió o aceptó el valor.
- vacio: el documento no trae ese dato (p. ej. actividad sin aula).
- pendiente: solo para grupos: se conoce la letra pero no el grupo completo.
"""

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.tipos import FechaHora, JSONCompatible
from app.models.base import Base, ConFechas
from app.models.catalogos import Docente


class Importacion(ConFechas, Base):
    """Un archivo subido (ZIP con PDFs o un PDF suelto)."""

    __tablename__ = "importacion"
    __table_args__ = (
        CheckConstraint(
            "estado IN ('procesando', 'en_revision', 'terminada', 'error', 'cancelada')",
            name="estado",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    periodo_id: Mapped[int] = mapped_column(ForeignKey("periodo.id"))
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuario.id"))
    nombre_archivo: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64))
    estado: Mapped[str] = mapped_column(String(20), default="procesando")
    total_documentos: Mapped[int] = mapped_column(Integer, default=0)
    procesados: Mapped[int] = mapped_column(Integer, default=0)
    mensaje: Mapped[str] = mapped_column(Text, default="")

    documentos: Mapped[list["DocumentoImportado"]] = relationship(
        back_populates="importacion",
        cascade="all, delete-orphan",
        order_by="DocumentoImportado.nombre_archivo",
    )


class DocumentoImportado(Base):
    """Un PDF dentro de la importación."""

    __tablename__ = "importacion_documento"
    __table_args__ = (
        CheckConstraint("estado IN ('procesado', 'duplicado', 'error')", name="estado"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    importacion_id: Mapped[int] = mapped_column(
        ForeignKey("importacion.id", ondelete="CASCADE"), index=True
    )
    nombre_archivo: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    paginas_total: Mapped[int] = mapped_column(Integer, default=0)
    estado: Mapped[str] = mapped_column(String(20), default="procesado")
    duplicado_de_id: Mapped[int | None] = mapped_column(ForeignKey("importacion_documento.id"))
    mensaje: Mapped[str] = mapped_column(Text, default="")

    importacion: Mapped[Importacion] = relationship(back_populates="documentos")
    paginas: Mapped[list["PaginaImportada"]] = relationship(
        back_populates="documento",
        cascade="all, delete-orphan",
        order_by="PaginaImportada.numero",
    )


class PaginaImportada(Base):
    """Una página = una propuesta de horario de un docente."""

    __tablename__ = "importacion_pagina"
    __table_args__ = (
        CheckConstraint(
            "estado IN ('por_revisar', 'aprobada', 'descartada', 'duplicada', 'error')",
            name="estado",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    documento_id: Mapped[int] = mapped_column(
        ForeignKey("importacion_documento.id", ondelete="CASCADE"), index=True
    )
    numero: Mapped[int] = mapped_column(Integer)
    estado: Mapped[str] = mapped_column(String(20), default="por_revisar")
    mensaje: Mapped[str] = mapped_column(Text, default="")

    # Encabezado leído (del QR si existe; si no, del OCR).
    qr_texto: Mapped[str | None] = mapped_column(Text)
    encabezado: Mapped[dict[str, Any] | None] = mapped_column(JSONCompatible)
    docente_texto: Mapped[str] = mapped_column(String(150), default="")
    nomina: Mapped[str | None] = mapped_column(String(20))
    periodo_texto: Mapped[str | None] = mapped_column(String(60))
    version_documento: Mapped[int | None] = mapped_column(Integer)
    fecha_documento: Mapped[date | None] = mapped_column(Date)
    horas_qr: Mapped[int | None] = mapped_column(Integer)

    docente_id: Mapped[int | None] = mapped_column(ForeignKey("docente.id"))
    docente_estado: Mapped[str] = mapped_column(String(20), default="sin_coincidencia")

    duplicado_de_id: Mapped[int | None] = mapped_column(ForeignKey("importacion_pagina.id"))
    horario_id: Mapped[int | None] = mapped_column(ForeignKey("horario.id"))
    revisado_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuario.id"))
    revisado_en: Mapped[datetime | None] = mapped_column(FechaHora())

    documento: Mapped[DocumentoImportado] = relationship(back_populates="paginas")
    docente: Mapped[Docente | None] = relationship(lazy="joined")
    celdas: Mapped[list["CeldaImportada"]] = relationship(
        back_populates="pagina",
        cascade="all, delete-orphan",
        order_by="(CeldaImportada.dia, CeldaImportada.hora)",
    )


class CeldaImportada(Base):
    """Una hora de la cuadrícula: lo que dijo el OCR y lo que se asignará."""

    __tablename__ = "importacion_celda"
    __table_args__ = (
        UniqueConstraint("pagina_id", "dia", "hora", name="uq_importacion_celda_posicion"),
        CheckConstraint("dia BETWEEN 0 AND 5", name="dia"),
        CheckConstraint("hora BETWEEN 7 AND 22", name="hora"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    pagina_id: Mapped[int] = mapped_column(
        ForeignKey("importacion_pagina.id", ondelete="CASCADE"), index=True
    )
    dia: Mapped[int] = mapped_column(Integer)
    hora: Mapped[int] = mapped_column(Integer)  # 7 = fila de 07:00 a 08:00
    origen: Mapped[str] = mapped_column(String(10), default="ocr")  # ocr | manual

    # Texto leído por el OCR (no se modifica: es la evidencia).
    texto_ocr: Mapped[str] = mapped_column(Text, default="")
    actividad_texto: Mapped[str] = mapped_column(String(150), default="")
    grupo_texto: Mapped[str | None] = mapped_column(String(10))
    aula_texto: Mapped[str | None] = mapped_column(String(40))
    imagen_png: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)

    # Valores asignados y su estado de comparación con los catálogos.
    asignatura_id: Mapped[int | None] = mapped_column(ForeignKey("asignatura.id"))
    asignatura_estado: Mapped[str] = mapped_column(String(20), default="sin_coincidencia")
    aula_id: Mapped[int | None] = mapped_column(ForeignKey("aula.id"))
    aula_estado: Mapped[str] = mapped_column(String(20), default="sin_coincidencia")
    grupo_id: Mapped[int | None] = mapped_column(ForeignKey("grupo.id"))
    grupo_letra: Mapped[str | None] = mapped_column(String(5))
    grupo_estado: Mapped[str] = mapped_column(String(20), default="vacio")

    pagina: Mapped[PaginaImportada] = relationship(back_populates="celdas")
