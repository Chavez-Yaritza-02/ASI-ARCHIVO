"""Configuración del servidor.

Los valores se leen de variables de entorno o del archivo `.env` (que nunca
se sube a GitHub). Ver `.env.example` en la raíz del proyecto.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

RAIZ_PROYECTO = Path(__file__).resolve().parents[3]


class Configuracion(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ASI_",
        env_file=RAIZ_PROYECTO / ".env",
        extra="ignore",
    )

    entorno: str = "desarrollo"
    database_url: str
    # Clave para firmar los tokens de sesión. Debe ser larga y aleatoria.
    secret_key: str = Field(min_length=32)
    token_minutos: int = 480  # una jornada laboral
    zona_horaria: str = "America/Mexico_City"


@lru_cache
def obtener_configuracion() -> Configuracion:
    return Configuracion()
