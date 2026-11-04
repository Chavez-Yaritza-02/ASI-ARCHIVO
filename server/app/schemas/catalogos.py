"""Esquemas de entrada y salida de docentes, catálogos y periodos."""

from datetime import date

from pydantic import AliasChoices, BaseModel, ConfigDict, EmailStr, Field, model_validator

from asi_shared import TipoAsignatura


class _Salida(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- Docentes ---


class DocenteCrear(BaseModel):
    nombre: str = Field(min_length=3, max_length=150)
    nomina: str | None = Field(default=None, max_length=20)
    correo: EmailStr | None = None


class DocenteEditar(BaseModel):
    nombre: str | None = Field(default=None, min_length=3, max_length=150)
    nomina: str | None = Field(default=None, max_length=20)
    correo: EmailStr | None = None
    activo: bool | None = None


class DocenteSalida(_Salida):
    id: int
    nombre: str
    nomina: str | None
    correo: str | None
    activo: bool


# --- Asignaturas, grupos y aulas ---


class AsignaturaCrear(BaseModel):
    nombre: str = Field(min_length=2, max_length=120)
    tipo: TipoAsignatura = TipoAsignatura.MATERIA


class AsignaturaEditar(BaseModel):
    nombre: str | None = Field(default=None, min_length=2, max_length=120)
    tipo: TipoAsignatura | None = None
    activo: bool | None = None


class AsignaturaSalida(_Salida):
    id: int
    nombre: str
    tipo: TipoAsignatura
    activo: bool


class ClaveCrear(BaseModel):
    """Grupos y aulas: una clave corta y una descripción opcional."""

    clave: str = Field(min_length=1, max_length=30)
    descripcion: str = Field(default="", max_length=200)


class ClaveEditar(BaseModel):
    clave: str | None = Field(default=None, min_length=1, max_length=30)
    descripcion: str | None = Field(default=None, max_length=200)
    activo: bool | None = None


class ClaveSalida(_Salida):
    id: int
    clave: str
    descripcion: str
    activo: bool


class GrupoCrear(BaseModel):
    """Un grupo se identifica por periodo + carrera + semestre + letra. Si falta alguno,
    se guarda igual pero queda pendiente de validación."""

    letra: str = Field(min_length=1, max_length=5, validation_alias=AliasChoices("letra", "clave"))
    periodo_id: int | None = None
    carrera: str | None = Field(default=None, max_length=60)
    semestre: int | None = Field(default=None, ge=1, le=12)
    descripcion: str = Field(default="", max_length=200)


class GrupoEditar(BaseModel):
    letra: str | None = Field(
        default=None, min_length=1, max_length=5, validation_alias=AliasChoices("letra", "clave")
    )
    periodo_id: int | None = None
    carrera: str | None = Field(default=None, max_length=60)
    semestre: int | None = Field(default=None, ge=1, le=12)
    descripcion: str | None = Field(default=None, max_length=200)
    activo: bool | None = None


class GrupoSalida(_Salida):
    id: int
    clave: str
    letra: str
    periodo_id: int | None
    carrera: str | None
    semestre: int | None
    descripcion: str
    activo: bool
    pendiente_validacion: bool


# --- Periodos ---


class PeriodoEntrada(BaseModel):
    nombre: str = Field(min_length=3, max_length=60)
    fecha_inicio: date
    fecha_fin: date

    @model_validator(mode="after")
    def _fechas(self):
        if self.fecha_fin <= self.fecha_inicio:
            raise ValueError("La fecha de fin debe ser posterior a la de inicio")
        return self


class PeriodoSalida(_Salida):
    id: int
    nombre: str
    fecha_inicio: date
    fecha_fin: date
    estado: str
