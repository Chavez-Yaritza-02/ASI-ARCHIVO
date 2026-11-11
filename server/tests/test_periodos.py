"""Periodos académicos (datos ficticios)."""

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.models import Auditoria

AGO_DIC = {
    "nombre": "Agosto - Diciembre 2026",
    "fecha_inicio": "2026-08-01",
    "fecha_fin": "2026-12-31",
}
ENE_JUN = {"nombre": "Enero - Junio 2027", "fecha_inicio": "2027-01-01", "fecha_fin": "2027-06-30"}


def test_crear_periodo_en_borrador(cliente, como_admin):
    r = cliente.post("/periodos", json=AGO_DIC, headers=como_admin)
    assert r.status_code == 201, r.text
    assert r.json()["estado"] == "borrador"
    assert r.json()["nombre"] == "AGOSTO - DICIEMBRE 2026"


def test_fechas_invalidas_nombre_repetido_y_traslape(cliente, como_admin):
    malo = {**AGO_DIC, "fecha_fin": "2026-07-01"}
    assert cliente.post("/periodos", json=malo, headers=como_admin).status_code == 422
    cliente.post("/periodos", json=AGO_DIC, headers=como_admin)
    assert cliente.post("/periodos", json=AGO_DIC, headers=como_admin).status_code == 409
    encimado = {"nombre": "Verano 2026", "fecha_inicio": "2026-12-01", "fecha_fin": "2027-01-15"}
    r = cliente.post("/periodos", json=encimado, headers=como_admin)
    assert r.status_code == 409 and "traslapan" in r.json()["detail"]


def test_solo_un_periodo_activo_y_cambio_de_semestre(cliente, como_admin):
    p1 = cliente.post("/periodos", json=AGO_DIC, headers=como_admin).json()
    p2 = cliente.post("/periodos", json=ENE_JUN, headers=como_admin).json()
    assert cliente.post(f"/periodos/{p1['id']}/activar", headers=como_admin).status_code == 200
    r = cliente.post(f"/periodos/{p2['id']}/activar", headers=como_admin)
    assert r.status_code == 409 and "Primero cierra" in r.json()["detail"]

    assert (
        cliente.post(f"/periodos/{p1['id']}/cerrar", headers=como_admin).json()["estado"]
        == "cerrado"
    )
    assert (
        cliente.post(f"/periodos/{p2['id']}/activar", headers=como_admin).json()["estado"]
        == "activo"
    )
    assert cliente.get("/periodos/activo", headers=como_admin).json()["id"] == p2["id"]
    # Un periodo cerrado no se reabre ni se edita.
    assert cliente.post(f"/periodos/{p1['id']}/activar", headers=como_admin).status_code == 409
    assert cliente.put(f"/periodos/{p1['id']}", json=AGO_DIC, headers=como_admin).status_code == 409


def test_la_base_de_datos_impide_dos_activos(sesion, cliente, como_admin):
    cliente.post("/periodos", json=AGO_DIC, headers=como_admin)
    cliente.post("/periodos", json=ENE_JUN, headers=como_admin)
    sesion.execute(text("UPDATE periodo SET estado = 'activo' WHERE id = 1"))
    try:
        sesion.execute(text("UPDATE periodo SET estado = 'activo' WHERE id = 2"))
        raise AssertionError("Debió fallar")
    except IntegrityError:
        sesion.rollback()


def test_consulta_ve_periodos_pero_no_los_gestiona(cliente, como_admin, como_consulta):
    cliente.post("/periodos", json=AGO_DIC, headers=como_admin)
    assert len(cliente.get("/periodos", headers=como_consulta).json()) == 1
    assert cliente.post("/periodos", json=ENE_JUN, headers=como_consulta).status_code == 403
    assert cliente.post("/periodos/1/activar", headers=como_consulta).status_code == 403


def test_periodos_quedan_auditados(cliente, como_admin, sesion):
    cliente.post("/periodos", json=AGO_DIC, headers=como_admin)
    cliente.post("/periodos/1/activar", headers=como_admin)
    cliente.post("/periodos/1/cerrar", headers=como_admin)
    acciones = sesion.scalars(
        select(Auditoria.accion).where(Auditoria.entidad == "periodo").order_by(Auditoria.id)
    )
    assert list(acciones) == ["crear", "activar", "cerrar"]
