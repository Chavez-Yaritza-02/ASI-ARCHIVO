"""Horarios versionados: borradores, validaciones, confirmación e historial (datos ficticios)."""

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.models import Auditoria


@pytest.fixture
def base(cliente, como_admin):
    """Periodo activo, dos docentes y catálogos mínimos. Devuelve sus ids."""

    def crear(ruta, datos):
        r = cliente.post(ruta, json=datos, headers=como_admin)
        assert r.status_code == 201, r.text
        return r.json()["id"]

    ids = {
        "periodo": crear(
            "/periodos",
            {
                "nombre": "Agosto - Diciembre 2026",
                "fecha_inicio": "2026-08-01",
                "fecha_fin": "2026-12-31",
            },
        ),
        "docente": crear("/docentes", {"nombre": "DOCENTE PRUEBA UNO"}),
        "docente2": crear("/docentes", {"nombre": "DOCENTE PRUEBA DOS"}),
        "calculo": crear("/asignaturas", {"nombre": "CÁLC. DIF."}),
        "fisica": crear("/asignaturas", {"nombre": "FIS. GRAL"}),
        "gestion": crear("/asignaturas", {"nombre": "GESTIÓN ACADÉMICA", "tipo": "actividad"}),
        "m01": crear("/aulas", {"clave": "M01"}),
        "m02": crear("/aulas", {"clave": "M02"}),
    }
    # Grupo completo (periodo + carrera + semestre + letra): no queda pendiente de validación.
    ids["grupo_a"] = crear(
        "/grupos", {"letra": "A", "periodo_id": ids["periodo"], "carrera": "IEM", "semestre": 3}
    )
    cliente.post(f"/periodos/{ids['periodo']}/activar", headers=como_admin)
    return ids


def bloque(dia, inicio, fin, asignatura, grupo=None, aula=None):
    return {
        "dia": dia,
        "hora_inicio": inicio,
        "hora_fin": fin,
        "asignatura_id": asignatura,
        "grupo_id": grupo,
        "aula_id": aula,
    }


@pytest.fixture
def bloques_validos(base):
    return [
        bloque("lunes", "07:00", "09:00", base["calculo"], base["grupo_a"], base["m01"]),
        bloque("lunes", "09:00", "10:00", base["gestion"], None, base["m02"]),
        bloque("miercoles", "07:00", "09:00", base["calculo"], base["grupo_a"], base["m01"]),
    ]


def nuevo_borrador(cliente, encabezados, base, docente="docente", **extra):
    datos = {"docente_id": base[docente], "periodo_id": base["periodo"], **extra}
    r = cliente.post("/horarios", json=datos, headers=encabezados)
    assert r.status_code == 201, r.text
    return r.json()


def test_crear_borrador_guardar_bloques_y_confirmar(cliente, como_admin, base, bloques_validos):
    h = nuevo_borrador(cliente, como_admin, base)
    assert (h["version"], h["estado"], h["bloques"]) == (1, "borrador", [])

    r = cliente.put(f"/horarios/{h['id']}/bloques", json=bloques_validos, headers=como_admin)
    assert r.status_code == 200, r.text
    detalle = r.json()
    assert len(detalle["bloques"]) == 3 and detalle["horas"] == 5
    assert detalle["bloques"][0]["asignatura"]["nombre"] == "CÁLC. DIF."
    assert detalle["bloques"][0]["aula"]["clave"] == "M01"

    r = cliente.post(f"/horarios/{h['id']}/confirmar", json={}, headers=como_admin)
    assert r.status_code == 200, r.text
    assert r.json()["estado"] == "vigente" and r.json()["confirmado_en"]


def test_traslapes_y_duplicados_se_rechazan(cliente, como_admin, base, bloques_validos):
    h = nuevo_borrador(cliente, como_admin, base)
    con_errores = [
        *bloques_validos,
        bloque("lunes", "08:00", "09:30", base["fisica"], base["grupo_a"], base["m02"]),  # traslape
        bloques_validos[2],  # repetido
        bloque("martes", "10:00", "09:00", base["fisica"], base["grupo_a"]),  # horas al revés
    ]
    r = cliente.put(f"/horarios/{h['id']}/bloques", json=con_errores, headers=como_admin)
    assert r.status_code == 422
    problemas = r.json()["problemas"]
    assert any("se traslapa" in p for p in problemas)
    assert any("repetido" in p for p in problemas)
    assert any("hora de fin" in p for p in problemas)
    # No se guardó nada.
    assert cliente.get(f"/horarios/{h['id']}", headers=como_admin).json()["bloques"] == []


def test_materia_sin_grupo_y_catalogo_inactivo(cliente, como_admin, base):
    h = nuevo_borrador(cliente, como_admin, base)
    cliente.post(f"/aulas/{base['m02']}/desactivar", headers=como_admin)
    r = cliente.put(
        f"/horarios/{h['id']}/bloques",
        json=[
            bloque("lunes", "07:00", "08:00", base["calculo"], None, base["m01"]),
            bloque("martes", "07:00", "08:00", base["gestion"], None, base["m02"]),
        ],
        headers=como_admin,
    )
    problemas = r.json()["problemas"]
    assert r.status_code == 422
    assert any("necesita grupo" in p for p in problemas)
    assert any("aula no existe o está inactiva" in p for p in problemas)


def test_vigente_no_se_edita_se_crea_nueva_version(cliente, como_admin, base, bloques_validos):
    v1 = nuevo_borrador(cliente, como_admin, base)
    cliente.put(f"/horarios/{v1['id']}/bloques", json=bloques_validos, headers=como_admin)
    cliente.post(f"/horarios/{v1['id']}/confirmar", json={}, headers=como_admin)

    r = cliente.put(f"/horarios/{v1['id']}/bloques", json=[], headers=como_admin)
    assert r.status_code == 409 and "nueva versión" in r.json()["detail"]

    v2 = nuevo_borrador(cliente, como_admin, base, basado_en_id=v1["id"])
    assert v2["version"] == 2 and len(v2["bloques"]) == 3  # copia de la vigente

    # Sin cambios: se advierte que es idéntica a la vigente.
    r = cliente.post(f"/horarios/{v2['id']}/confirmar", json={}, headers=como_admin)
    assert r.status_code == 409
    assert any("idéntica" in p for p in r.json()["problemas"])

    # Con un cambio real se confirma y la anterior pasa a histórico.
    cambiados = bloques_validos[:2]
    cliente.put(f"/horarios/{v2['id']}/bloques", json=cambiados, headers=como_admin)
    assert (
        cliente.post(f"/horarios/{v2['id']}/confirmar", json={}, headers=como_admin).json()[
            "estado"
        ]
        == "vigente"
    )

    historial = cliente.get(f"/horarios?docente_id={base['docente']}", headers=como_admin).json()
    assert [(h["version"], h["estado"]) for h in historial] == [(2, "vigente"), (1, "historico")]
    # El historial conserva los bloques originales de la versión 1.
    assert len(cliente.get(f"/horarios/{v1['id']}", headers=como_admin).json()["bloques"]) == 3


def test_aula_ocupada_por_otro_docente_requiere_aceptar(cliente, como_admin, base, bloques_validos):
    otro = nuevo_borrador(cliente, como_admin, base, docente="docente2")
    cliente.put(
        f"/horarios/{otro['id']}/bloques",
        json=[bloque("lunes", "08:00", "10:00", base["fisica"], base["grupo_a"], base["m01"])],
        headers=como_admin,
    )
    cliente.post(f"/horarios/{otro['id']}/confirmar", json={}, headers=como_admin)

    h = nuevo_borrador(cliente, como_admin, base)
    r = cliente.put(f"/horarios/{h['id']}/bloques", json=bloques_validos, headers=como_admin)
    assert any("Aula M01 ocupada" in a for a in r.json()["advertencias"])

    r = cliente.post(f"/horarios/{h['id']}/confirmar", json={}, headers=como_admin)
    assert r.status_code == 409 and "DOCENTE PRUEBA DOS" in r.json()["problemas"][0]
    r = cliente.post(
        f"/horarios/{h['id']}/confirmar", json={"aceptar_advertencias": True}, headers=como_admin
    )
    assert r.json()["estado"] == "vigente"


def test_confirmar_vacio_descartar_y_periodo_cerrado(cliente, como_admin, base, bloques_validos):
    h = nuevo_borrador(cliente, como_admin, base)
    r = cliente.post(f"/horarios/{h['id']}/confirmar", json={}, headers=como_admin)
    assert r.status_code == 422 and "sin actividades" in r.json()["detail"]
    assert (
        cliente.post(f"/horarios/{h['id']}/descartar", headers=como_admin).json()["estado"]
        == "descartado"
    )

    cliente.post(f"/periodos/{base['periodo']}/cerrar", headers=como_admin)
    r = cliente.post(
        "/horarios",
        json={"docente_id": base["docente"], "periodo_id": base["periodo"]},
        headers=como_admin,
    )
    assert r.status_code == 409 and "cerrado" in r.json()["detail"]


def test_docente_inactivo_no_recibe_horarios(cliente, como_admin, base):
    cliente.post(f"/docentes/{base['docente']}/desactivar", headers=como_admin)
    r = cliente.post(
        "/horarios",
        json={"docente_id": base["docente"], "periodo_id": base["periodo"]},
        headers=como_admin,
    )
    assert r.status_code == 409 and "inactivo" in r.json()["detail"]


def test_permisos_de_horarios(cliente, como_admin, como_consulta, base, bloques_validos):
    h = nuevo_borrador(cliente, como_admin, base)
    cliente.put(f"/horarios/{h['id']}/bloques", json=bloques_validos, headers=como_admin)
    assert cliente.get(f"/horarios/{h['id']}", headers=como_consulta).status_code == 200
    assert (
        cliente.post(
            "/horarios",
            json={"docente_id": base["docente"], "periodo_id": base["periodo"]},
            headers=como_consulta,
        ).status_code
        == 403
    )
    assert (
        cliente.post(f"/horarios/{h['id']}/confirmar", json={}, headers=como_consulta).status_code
        == 403
    )


def test_la_base_de_datos_impide_dos_vigentes(cliente, como_admin, base, bloques_validos, sesion):
    for _ in range(2):
        nuevo_borrador(cliente, como_admin, base)
    sesion.execute(text("UPDATE horario SET estado = 'vigente' WHERE id = 1"))
    with pytest.raises(IntegrityError):
        sesion.execute(text("UPDATE horario SET estado = 'vigente' WHERE id = 2"))
    sesion.rollback()


def test_cambios_de_horario_quedan_auditados(cliente, como_admin, base, bloques_validos, sesion):
    v1 = nuevo_borrador(cliente, como_admin, base)
    cliente.put(f"/horarios/{v1['id']}/bloques", json=bloques_validos, headers=como_admin)
    cliente.post(f"/horarios/{v1['id']}/confirmar", json={}, headers=como_admin)
    v2 = nuevo_borrador(cliente, como_admin, base, basado_en_id=v1["id"])
    cliente.put(f"/horarios/{v2['id']}/bloques", json=bloques_validos[:1], headers=como_admin)
    cliente.post(f"/horarios/{v2['id']}/confirmar", json={}, headers=como_admin)

    registros = sesion.scalars(
        select(Auditoria).where(Auditoria.entidad == "horario").order_by(Auditoria.id)
    ).all()
    assert [(a.entidad_id, a.accion) for a in registros] == [
        ("1", "crear"),
        ("1", "editar_bloques"),
        ("1", "confirmar"),
        ("2", "crear"),
        ("2", "editar_bloques"),
        ("1", "reemplazar"),
        ("2", "confirmar"),
    ]
    edicion = registros[4]
    assert len(edicion.antes["bloques"]) == 3 and len(edicion.despues["bloques"]) == 1
    assert all(a.usuario_id is not None for a in registros)


def test_materia_con_solo_la_letra_queda_pendiente_y_se_advierte(cliente, como_admin, base):
    h = nuevo_borrador(cliente, como_admin, base)
    r = cliente.put(
        f"/horarios/{h['id']}/bloques",
        json=[
            {
                **bloque("lunes", "07:00", "08:00", base["calculo"], None, base["m01"]),
                "grupo_letra": "b",
            }
        ],
        headers=como_admin,
    )
    assert r.status_code == 200, r.text
    assert r.json()["bloques"][0]["grupo_letra"] == "B"
    assert any("pendiente de validación" in a for a in r.json()["advertencias"])
    r = cliente.post(f"/horarios/{h['id']}/confirmar", json={}, headers=como_admin)
    assert r.status_code == 409
    r = cliente.post(
        f"/horarios/{h['id']}/confirmar", json={"aceptar_advertencias": True}, headers=como_admin
    )
    assert r.json()["estado"] == "vigente"

    # Si se elige un grupo completo, la letra pendiente se descarta.
    v2 = nuevo_borrador(cliente, como_admin, base, basado_en_id=h["id"])
    r = cliente.put(
        f"/horarios/{v2['id']}/bloques",
        json=[
            {
                **bloque("lunes", "07:00", "08:00", base["calculo"], base["grupo_a"], base["m01"]),
                "grupo_letra": "B",
            }
        ],
        headers=como_admin,
    )
    assert r.json()["bloques"][0]["grupo_letra"] is None
    assert not any("pendiente" in a for a in r.json()["advertencias"])
