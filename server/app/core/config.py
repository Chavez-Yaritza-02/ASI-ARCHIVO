"""Configuración del servidor.

Los valores se leen de variables de entorno o del archivo `.env` (que nunca
se sube a GitHub). Ver `.env.example` en la raíz del proyecto.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

RAIZ_PROYECTO = Path(__file__).resolve().parents[3]


class Configuracion(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ASI_",
        env_file=RAIZ_PROYECTO / ".env",
        extra="ignore",
    )

    entorno: str = "desarrollo"
    instancia_aceptacion: bool = False
    hosts_permitidos: list[str] = []
    archivo_raiz: Path = Path.home() / ".local" / "share" / "asi-archivo" / "documentos"
    archivo_max_mb: int = Field(default=20, ge=1, le=50)
    archivo_antivirus_cmd: Path | None = None
    archivo_requerir_antivirus: bool = True
    database_url: str
    # Clave para firmar los tokens de sesión. Debe ser larga y aleatoria.
    secret_key: str = Field(min_length=32)
    token_minutos: int = 480  # una jornada laboral
    zona_horaria: str = "America/Mexico_City"
    # Encabezado de los reportes impresos.
    institucion: str = "Tecnológico Superior de Jalisco · Unidad Académica Zapopan"
    dependencia: str = "Jefatura de Electromecánica"

    @model_validator(mode="after")
    def validar_produccion(self):
        if self.entorno == "produccion":
            if not self.hosts_permitidos or any("*" in h for h in self.hosts_permitidos):
                raise ValueError("Producción requiere una lista explícita de hosts permitidos")
            if "cambia-esta-clave" in self.secret_key or len(set(self.secret_key)) < 12:
                raise ValueError("Producción requiere una clave secreta aleatoria")
            if not self.archivo_requerir_antivirus or not self.archivo_antivirus_cmd:
                raise ValueError("Producción requiere antivirus configurado y obligatorio")
            if not self.archivo_raiz.is_absolute() or not self.archivo_antivirus_cmd.is_absolute():
                raise ValueError("Producción requiere rutas absolutas para almacén y antivirus")
        return self


@lru_cache
def obtener_configuracion() -> Configuracion:
    return Configuracion()
