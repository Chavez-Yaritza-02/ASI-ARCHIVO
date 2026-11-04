"""Bitácora diaria, registro y corrección de asistencias, calendario, incidencias y reportes.

Datos ficticios. "Hoy" se fija en el miércoles 4 de noviembre de 2026.
Lunes 2/11 · Martes 3/11 · Miércoles 4/11 · Domingo 8/11 · Lunes 9/11.
"""

import io
from datetime import date

import pytest
from openpyxl import load_workbook
from sqlalchemy import text

from app.services import bitacora as servicio_bitacora

HOY = date(2026, 11, 4)
LUNES, MARTES, DOMINGO, LUNES_SIGUIENTE = "2026-11-02", "2026-11-03", "2026-11-08", "2026-11-09"
CONTRASENA = "contrasena-de-prueba"


@pytest.fixture(autouse=True)
def hoy_fijo(monkeypatch):
    monkeypatch.setattr(servicio_bitacora, "hoy", lambda: HOY)


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
def escuela(cliente, como_admin):
    """Periodo activo con dos docentes y horarios vigentes."""

    def post(ruta, datos):
        r = cliente.post(ruta, json=datos, headers=como_admin)
        assert r.status_code in (200, 201), r.text
        return r.json()

    periodo = post(
        "/periodos",
        {
            "nombre": "Agosto - Diciembre 2026",
            "fecha_inicio": "2026-08-01",
            "fecha_fin": "2026-12-31",
        },
    )
    post(f"/periodos/{periodo['id']}/activar", {})
    ids = {
        "periodo": periodo["id"],
        "uno": post("/docentes", {"nombre": "DOCENTE PRUEBA UNO"})["id"],
        "dos": post("/docentes", {"nombre": "DOCENTE PRUEBA DOS"})["id"],
        "calculo": post("/asignaturas", {"nombre": "CÁLC. DIF."})["id"],
        "fisica": post("/asignaturas", {"nombre": "FIS. GRAL"})["id"],
        "gestion": post("/asignaturas", {"nombre": "GESTIÓN", "tipo": "actividad"})["id"],
        "m01": post("/aulas", {"clave": "M01"})["id"],
    }
    ids["grupo"] = post(
        "/grupos", {"letra": "A", "periodo_id": periodo["id"], "carrera": "IEM", "semestre": 3}
    )["id"]

    def horario(docente, bloques):
        h = post("/horarios", {"docente_id": ids[docente], "periodo_id": ids["periodo"]})
        cliente.put(f"/horarios/{h['id']}/bloques", json=bloques, headers=como_admin)
        return post(
            f"/horarios/{h['id']}/confirmar",
            {"aceptar_advertencias": True, "vigente_desde": "2026-08-01"},
        )

    ids["horario_uno"] = horario(
        "uno",
        [
            bloque("lunes", "07:00", "09:00", ids["calculo"], ids["grupo"], ids["m01"]),
            bloque("lunes", "15:00", "17:00", ids["fisica"], ids["grupo"], ids["m01"]),
            bloque("miercoles", "09:00", "10:00", ids["gestion"]),
        ],
    )["id"]
    horario("dos", [bloque("miercoles", "14:00", "16:00", ids["fisica"], ids["grupo"])])
    return ids


def ver(cliente, encabezados, fecha, **filtros):
    r = cliente.get("/bitacora", params={"fecha": fecha, **filtros}, headers=encabezados)
    assert r.status_code == 200, r.text
    return r.json()


def registrar(cliente, encabezados, docente, fecha, turno, **datos):
    return cliente.post(
        "/asistencias",
        json={"docente_id": docente, "fecha": fecha, "turno": turno, **datos},
        headers=encabezados,
    )


# --- Lista del día ---------------------------------------------------------------------


def test_lista_del_dia_sale_de_los_horarios_vigentes(cliente, como_admin, escuela):
    b = ver(cliente, como_admin, LUNES)
    assert b["dia_habil"] and b["periodo"]["id"] == escuela["periodo"]
    filas = [
        (
            f["docente"]["nombre"],
            f["turno"],
            f["programado_inicio"],
            f["programado_fin"],
            f["estado"],
        )
        for f in b["filas"]
    ]
    assert filas == [
        ("DOCENTE PRUEBA UNO", "matutino", "07:00:00", "09:00:00", "pendiente"),
        ("DOCENTE PRUEBA UNO", "vespertino", "15:00:00", "17:00:00", "pendiente"),
    ]
    actividad = b["filas"][0]["actividades"][0]
    assert (actividad["asignatura"], actividad["grupo"], actividad["aula"]) == (
        "CÁLC. DIF.",
        "IEM 3A",
        "M01",
    )
    assert b["resumen"]["pendiente"] == 2 and b["resumen"]["falto"] == 0

    # El turno se decide por la hora de inicio: 14:00 ya es vespertino.
    miercoles = ver(cliente, como_admin, HOY.isoformat())
    assert {(f["docente"]["nombre"], f["turno"]) for f in miercoles["filas"]} == {
        ("DOCENTE PRUEBA UNO", "matutino"),
        ("DOCENTE PRUEBA DOS", "vespertino"),
    }
    assert len(ver(cliente, como_admin, HOY.isoformat(), turno="vespertino")["filas"]) == 1
    assert len(ver(cliente, como_admin, HOY.isoformat(), docente_id=escuela["uno"])["filas"]) == 1


def test_domingo_y_fechas_fuera_del_periodo(cliente, como_admin, escuela):
    domingo = ver(cliente, como_admin, DOMINGO)
    assert (domingo["dia_habil"], domingo["motivo"], domingo["filas"]) == (False, "Domingo", [])
    fuera = ver(cliente, como_admin, "2027-01-15")
    assert fuera["periodo"] is None and fuera["filas"] == []


# --- Registro --------------------------------------------------------------------------


def test_registrar_estados_y_resumen(cliente, como_admin, escuela):
    u = escuela["uno"]
    r = registrar(
        cliente,
        como_admin,
        u,
        LUNES,
        "matutino",
        estado="retardo",
        hora_entrada="07:25",
        hora_salida="09:00",
        observaciones="Tráfico",
    )
    assert r.status_code == 201, r.text
    r = registrar(cliente, como_admin, u, LUNES, "vespertino", estado="falto")
    assert r.status_code == 201
    b = ver(cliente, como_admin, LUNES)
    assert [f["estado"] for f in b["filas"]] == ["retardo", "falto"]
    assert b["filas"][0]["minutos_retardo"] == 25
    assert b["filas"][0]["asistencia"]["observaciones"] == "Tráfico"
    assert b["resumen"]["retardo"] == 1 and b["resumen"]["falto"] == 1
    assert b["resumen"]["pendiente"] == 0
    assert [f["estado"] for f in ver(cliente, como_admin, LUNES, estado="falto")["filas"]] == [
        "falto"
    ]


@pytest.mark.parametrize(
    ("datos", "mensaje"),
    [
        ({"estado": "falto", "hora_entrada": "07:00"}, "no lleva hora"),
        ({"estado": "retardo"}, "hora real de entrada"),
        ({"estado": "justificado"}, "justificación"),
        ({"estado": "asistio", "hora_entrada": "09:00", "hora_salida": "08:00"}, "posterior"),
    ],
)
def test_validaciones_del_registro(cliente, como_admin, escuela, datos, mensaje):
    r = registrar(cliente, como_admin, escuela["uno"], LUNES, "matutino", **datos)
    assert r.status_code == 422 and mensaje in r.json()["detail"]


def test_no_duplicados_ni_registros_sin_programacion_o_futuros(cliente, como_admin, escuela):
    u = escuela["uno"]
    assert registrar(cliente, como_admin, u, LUNES, "matutino", estado="asistio").status_code == 201
    r = registrar(cliente, como_admin, u, LUNES, "matutino", estado="falto")
    assert r.status_code == 409 and "corrígelo" in r.json()["detail"]
    r = registrar(cliente, como_admin, escuela["dos"], LUNES, "matutino", estado="asistio")
    assert r.status_code == 422 and "no tiene actividades" in r.json()["detail"]
    r = registrar(cliente, como_admin, u, LUNES_SIGUIENTE, "matutino", estado="asistio")
    assert r.status_code == 422 and "futuras" in r.json()["detail"]
    # Un permiso futuro sí se puede registrar como justificado.
    r = registrar(
        cliente,
        como_admin,
        u,
        LUNES_SIGUIENTE,
        "matutino",
        estado="justificado",
        justificacion="Oficio de comisión 123",
    )
    assert r.status_code == 201


# --- Calendario ------------------------------------------------------------------------


def test_dia_inhabil_no_genera_faltas_y_excepciones(cliente, como_admin, escuela):
    evento = cliente.post(
        "/calendario",
        json={
            "tipo": "inhabil",
            "fecha_inicio": LUNES,
            "fecha_fin": LUNES,
            "descripcion": "Día festivo",
        },
        headers=como_admin,
    ).json()
    b = ver(cliente, como_admin, LUNES)
    assert not b["dia_habil"] and "Día festivo" in b["motivo"]
    assert [f["estado"] for f in b["filas"]] == ["inhabil", "inhabil"]
    assert b["resumen"]["inhabil"] == 2 and b["resumen"]["falto"] == 0

    r = registrar(cliente, como_admin, escuela["uno"], LUNES, "matutino", estado="asistio")
    assert r.status_code == 409
    # Excepción autorizada: clase de reposición registrada en día inhábil.
    r = registrar(
        cliente,
        como_admin,
        escuela["uno"],
        LUNES,
        "matutino",
        estado="asistio",
        autorizar_dia_inhabil=True,
    )
    assert r.status_code == 201 and r.json()["en_dia_inhabil"] is True

    # Una excepción "hábil" en el turno vespertino gana sobre el día festivo.
    cliente.post(
        "/calendario",
        json={
            "tipo": "habil",
            "fecha_inicio": LUNES,
            "fecha_fin": LUNES,
            "turno": "vespertino",
            "descripcion": "Reposición",
        },
        headers=como_admin,
    )
    assert ver(cliente, como_admin, LUNES)["filas"][1]["estado"] == "pendiente"

    cliente.post(f"/calendario/{evento['id']}/anular", headers=como_admin)
    assert ver(cliente, como_admin, LUNES)["dia_habil"] is True


def test_suspension_de_un_solo_turno_y_vacaciones(cliente, como_admin, escuela):
    cliente.post(
        "/calendario",
        json={
            "tipo": "suspension",
            "fecha_inicio": LUNES,
            "fecha_fin": LUNES,
            "turno": "vespertino",
            "descripcion": "Falla eléctrica",
        },
        headers=como_admin,
    )
    assert [f["estado"] for f in ver(cliente, como_admin, LUNES)["filas"]] == [
        "pendiente",
        "inhabil",
    ]
    cliente.post(
        "/calendario",
        json={
            "tipo": "vacaciones",
            "fecha_inicio": "2026-12-14",
            "fecha_fin": "2026-12-31",
            "descripcion": "Invierno",
        },
        headers=como_admin,
    )
    assert ver(cliente, como_admin, "2026-12-14")["dia_habil"] is False


def test_calendario_validaciones_y_permisos(cliente, como_admin, como_consulta, escuela):
    malo = {
        "tipo": "inhabil",
        "fecha_inicio": "2026-11-10",
        "fecha_fin": "2026-11-09",
        "descripcion": "Al revés",
    }
    assert cliente.post("/calendario", json=malo, headers=como_admin).status_code == 422
    bueno = {**malo, "fecha_fin": "2026-11-10"}
    assert cliente.post("/calendario", json=bueno, headers=como_consulta).status_code == 403
    assert cliente.post("/calendario", json=bueno, headers=como_admin).status_code == 201
    assert len(cliente.get("/calendario", headers=como_consulta).json()) == 1


# --- Correcciones e historial -------------------------------------------------------------


@pytest.fixture
def como_capturista(cliente, sesion):
    """Usuario que registra asistencia pero no tiene permiso de corrección."""
    from app.cli import crear_usuario

    sesion.execute(text("INSERT INTO rol (nombre, descripcion) VALUES ('capturista', 'x')"))
    sesion.execute(
        text(
            "INSERT INTO rol_permiso SELECT r.id, p.id FROM rol r, permiso p WHERE "
            "r.nombre = 'capturista' AND p.clave IN ('asistencia.ver', 'asistencia.registrar')"
        )
    )
    sesion.commit()
    crear_usuario(sesion, "captura@prueba.mx", "Captura", "consulta", CONTRASENA)
    sesion.execute(
        text(
            "UPDATE usuario_rol SET rol_id = (SELECT id FROM rol WHERE nombre = 'capturista') "
            "WHERE usuario_id = (SELECT id FROM usuario WHERE correo = 'captura@prueba.mx')"
        )
    )
    sesion.commit()
    r = cliente.post("/auth/login", data={"username": "captura@prueba.mx", "password": CONTRASENA})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_correcciones_con_motivo_permiso_e_historial(cliente, como_admin, como_capturista, escuela):
    hoy = registrar(
        cliente,
        como_capturista,
        escuela["uno"],
        HOY.isoformat(),
        "matutino",
        estado="asistio",
        hora_entrada="09:00",
    ).json()
    lunes = registrar(
        cliente, como_capturista, escuela["uno"], LUNES, "matutino", estado="asistio"
    ).json()

    # Sin motivo no hay corrección.
    r = cliente.patch(
        f"/asistencias/{hoy['id']}", json={"estado": "falto"}, headers=como_capturista
    )
    assert r.status_code == 422
    # El mismo día, quien registra puede corregir (una falta borra las horas).
    r = cliente.patch(
        f"/asistencias/{hoy['id']}",
        json={"estado": "falto", "motivo": "Se registró al docente equivocado"},
        headers=como_capturista,
    )
    assert r.status_code == 200 and r.json()["hora_entrada"] is None
    assert r.json()["correcciones"] == 1
    # Días anteriores requieren autorización.
    cambio = {
        "estado": "justificado",
        "justificacion": "Incapacidad",
        "motivo": "Entregó incapacidad médica",
    }
    r = cliente.patch(f"/asistencias/{lunes['id']}", json=cambio, headers=como_capturista)
    assert r.status_code == 403
    r = cliente.patch(f"/asistencias/{lunes['id']}", json=cambio, headers=como_admin)
    assert r.status_code == 200 and r.json()["estado"] == "justificado"

    historial = cliente.get(f"/asistencias/{lunes['id']}/historial", headers=como_admin).json()
    assert [h["accion"] for h in historial] == ["registrar", "corregir"]
    assert historial[1]["antes"]["estado"] == "asistio"
    assert historial[1]["despues"]["motivo"] == "Entregó incapacidad médica"
    assert historial[0]["usuario"] == "Captura"


def test_la_bitacora_usa_el_horario_que_regia_en_cada_fecha(cliente, como_admin, escuela):
    registrar(cliente, como_admin, escuela["uno"], LUNES, "vespertino", estado="asistio")
    # Nueva versión desde el martes: se elimina la clase del lunes por la tarde.
    v2 = cliente.post(
        "/horarios",
        json={
            "docente_id": escuela["uno"],
            "periodo_id": escuela["periodo"],
            "basado_en_id": escuela["horario_uno"],
        },
        headers=como_admin,
    ).json()
    cliente.put(
        f"/horarios/{v2['id']}/bloques",
        headers=como_admin,
        json=[
            bloque("lunes", "07:00", "09:00", escuela["calculo"], escuela["grupo"], escuela["m01"]),
            bloque("miercoles", "09:00", "10:00", escuela["gestion"]),
        ],
    )
    r = cliente.post(
        f"/horarios/{v2['id']}/confirmar", headers=como_admin, json={"vigente_desde": "2026-08-01"}
    )
    assert r.status_code == 422  # debe regir después de la versión actual
    r = cliente.post(
        f"/horarios/{v2['id']}/confirmar", headers=como_admin, json={"vigente_desde": MARTES}
    )
    assert r.status_code == 200 and r.json()["vigente_desde"] == MARTES
    v1 = cliente.get(f"/horarios/{escuela['horario_uno']}", headers=como_admin).json()
    assert v1["vigente_hasta"] == LUNES

    assert [f["turno"] for f in ver(cliente, como_admin, LUNES)["filas"]] == [
        "matutino",
        "vespertino",
    ]
    assert [f["turno"] for f in ver(cliente, como_admin, LUNES_SIGUIENTE)["filas"]] == ["matutino"]


def test_periodo_cerrado_es_de_solo_lectura(cliente, como_admin, escuela):
    cliente.post(f"/periodos/{escuela['periodo']}/cerrar", headers=como_admin)
    r = registrar(cliente, como_admin, escuela["uno"], LUNES, "matutino", estado="asistio")
    assert r.status_code == 409 and "cerrado" in r.json()["detail"]
    assert len(ver(cliente, como_admin, LUNES)["filas"]) == 2  # se puede consultar


# --- Incidencias -----------------------------------------------------------------------------


def test_incidencias_manuales(cliente, como_admin, escuela):
    r = cliente.post(
        "/incidencias",
        headers=como_admin,
        json={
            "fecha": LUNES,
            "docente_id": escuela["uno"],
            "turno": "matutino",
            "tipo": "cambio_aula",
            "descripcion": "Clase en LMAC por mantenimiento de M01",
        },
    )
    assert r.status_code == 201, r.text
    general = cliente.post(
        "/incidencias",
        headers=como_admin,
        json={"fecha": LUNES, "tipo": "otra", "descripcion": "Simulacro de evacuación"},
    ).json()
    b = ver(cliente, como_admin, LUNES)
    assert [i["tipo"] for i in b["incidencias"]] == ["cambio_aula", "otra"]
    assert len(ver(cliente, como_admin, LUNES, turno="vespertino")["incidencias"]) == 1

    cliente.patch(
        f"/incidencias/{general['id']}", json={"descripcion": "Simulacro 10:00"}, headers=como_admin
    )
    cliente.post(f"/incidencias/{general['id']}/anular", headers=como_admin)
    assert len(ver(cliente, como_admin, LUNES)["incidencias"]) == 1
    lista = cliente.get(
        "/incidencias", params={"desde": LUNES, "hasta": HOY.isoformat()}, headers=como_admin
    ).json()
    assert len(lista) == 1


# --- Reportes y permisos ---------------------------------------------------------------------


def test_exportar_bitacora_pdf_y_excel(cliente, como_admin, escuela):
    registrar(
        cliente,
        como_admin,
        escuela["uno"],
        LUNES,
        "matutino",
        estado="asistio",
        hora_entrada="07:00",
    )
    r = cliente.get(
        "/bitacora/exportar", params={"fecha": LUNES, "formato": "pdf"}, headers=como_admin
    )
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    assert r.headers["content-type"] == "application/pdf"

    r = cliente.get(
        "/bitacora/exportar", params={"fecha": LUNES, "formato": "xlsx"}, headers=como_admin
    )
    libro = load_workbook(io.BytesIO(r.content))
    textos = [str(c.value) for fila in libro["Bitácora"].iter_rows() for c in fila if c.value]
    assert "Bitácora diaria de asistencia docente" in textos
    assert "Asistió" in textos and "Pendiente de verificar" in textos  # se distinguen
    assert "Vo. Bo." in textos  # espacio para firmas
    resumen = {f[0].value: f[1].value for f in libro["Resumen"].iter_rows(min_row=2) if f[0].value}
    assert resumen["Asistió"] == 1 and resumen["Pendiente de verificar"] == 1

    r = cliente.get(
        "/bitacora/reporte",
        headers=como_admin,
        params={
            "desde": LUNES,
            "hasta": HOY.isoformat(),
            "docente_id": escuela["uno"],
            "formato": "xlsx",
        },
    )
    filas = list(load_workbook(io.BytesIO(r.content))["Bitácora"].iter_rows(values_only=True))
    assert sum(1 for f in filas if f[1] == "DOCENTE PRUEBA UNO") == 3  # lun ×2 y miércoles
    r = cliente.get(
        "/bitacora/reporte",
        headers=como_admin,
        params={"desde": "2026-08-01", "hasta": "2026-12-31"},
    )
    assert r.status_code == 422  # rango demasiado largo


def test_permisos_de_la_bitacora(cliente, como_consulta, escuela):
    assert (
        cliente.get("/bitacora", params={"fecha": LUNES}, headers=como_consulta).status_code == 200
    )
    r = registrar(cliente, como_consulta, escuela["uno"], LUNES, "matutino", estado="asistio")
    assert r.status_code == 403
    assert (
        cliente.get(
            "/bitacora/exportar", params={"fecha": LUNES}, headers=como_consulta
        ).status_code
        == 403
    )
    assert (
        cliente.post(
            "/incidencias",
            headers=como_consulta,
            json={"fecha": LUNES, "tipo": "otra", "descripcion": "x y z"},
        ).status_code
        == 403
    )
