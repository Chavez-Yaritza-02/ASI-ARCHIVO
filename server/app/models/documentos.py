"""Archivo privado: documentos lógicos, versiones inmutables y vínculos a horas."""

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, ConFechas, FechaHora


class CategoriaDocumento(Base):
    __tablename__ = "categoria_documento"
    id: Mapped[int] = mapped_column(primary_key=True)
    clave: Mapped[str] = mapped_column(String(40), unique=True)
    nombre: Mapped[str] = mapped_column(String(100))
    admite_justificantes: Mapped[bool] = mapped_column(Boolean, default=False)


class Documento(ConFechas, Base):
    __tablename__ = "documento"
    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(200))
    nombre_normalizado: Mapped[str] = mapped_column(String(200), index=True)
    descripcion: Mapped[str] = mapped_column(Text, default="")
    fecha: Mapped[date] = mapped_column(Date, index=True)
    categoria_id: Mapped[int] = mapped_column(ForeignKey("categoria_documento.id"))
    docente_id: Mapped[int | None] = mapped_column(ForeignKey("docente.id"), index=True)
    periodo_id: Mapped[int | None] = mapped_column(ForeignKey("periodo.id"), index=True)
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    creado_por_id: Mapped[int] = mapped_column(ForeignKey("usuario.id"))
    categoria: Mapped[CategoriaDocumento] = relationship(lazy="joined")


class VersionDocumento(Base):
    __tablename__ = "documento_version"
    __table_args__ = (
        UniqueConstraint("documento_id", "numero", name="uq_documento_version_numero"),
        CheckConstraint("numero > 0 AND bytes > 0 AND paginas > 0", name="datos"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    documento_id: Mapped[int] = mapped_column(ForeignKey("documento.id"), index=True)
    numero: Mapped[int] = mapped_column(Integer)
    clave: Mapped[str] = mapped_column(
        String(32), unique=True
    )  # solo UUID aleatorio, nunca una ruta
    nombre_original: Mapped[str] = mapped_column(String(200))
    mime: Mapped[str] = mapped_column(String(40))
    sha256: Mapped[str] = mapped_column(String(64))
    bytes: Mapped[int] = mapped_column(Integer)
    paginas: Mapped[int] = mapped_column(Integer)
    motivo: Mapped[str] = mapped_column(String(1000))
    subido_por_id: Mapped[int] = mapped_column(ForeignKey("usuario.id"))
    creado_en: Mapped[datetime] = mapped_column(FechaHora(), server_default=func.now())


class DocumentoAsistencia(Base):
    __tablename__ = "documento_asistencia"
    __table_args__ = (
        UniqueConstraint(
            "version_id", "asistencia_id", name="uq_documento_asistencia_version_hora"
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("documento_version.id"), index=True)
    asistencia_id: Mapped[int] = mapped_column(ForeignKey("asistencia_hora.id"), index=True)
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    vinculado_por_id: Mapped[int] = mapped_column(ForeignKey("usuario.id"))
    creado_en: Mapped[datetime] = mapped_column(FechaHora(), server_default=func.now())
