"""Tolerancia provisional configurable por un administrador y auditada."""

from sqlalchemy import select

from app.models.configuracion import ConfiguracionAsistencia
from app.services.comun import auditar


def tolerancia(sesion):
    return sesion.get(ConfiguracionAsistencia, 1).tolerancia_minutos


def actualizar_tolerancia(sesion, usuario, minutos):
    cfg = sesion.scalar(
        select(ConfiguracionAsistencia).where(ConfiguracionAsistencia.id == 1).with_for_update()
    )
    antes = cfg.tolerancia_minutos
    cfg.tolerancia_minutos = minutos
    if antes != minutos:
        auditar(
            sesion,
            usuario,
            "configurar",
            "configuracion_asistencia",
            1,
            {"tolerancia_minutos": antes},
            {"tolerancia_minutos": minutos},
        )
    sesion.commit()
    return {"tolerancia_minutos": minutos}
