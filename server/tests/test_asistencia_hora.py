"""Asistencia por hora contra API y PostgreSQL: todos los datos son ficticios."""

import io
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pymupdf
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.cli import crear_usuario
from app.main import app
from app.models import Asistencia, AsistenciaHora, Horario, Permiso, Rol
from app.services import asistencia_hora as servicio
from server.tests.test_consultas import get
from server.tests.test_horarios import nuevo_borrador

pytest_plugins = ["server.tests.test_consultas"]
LUNES = "2026-11-02"


@pytest.fixture
def escuela_horas(escuela_consulta, monkeypatch):
    monkeypatch.setattr(servicio, "hoy", lambda: date(2026, 11, 4))
    return escuela_consulta


def ver(cliente, headers, fecha=LUNES, **filtros):
    return get(cliente, headers, "/bitacora/horas", fecha=fecha, **filtros)


def capturar(cliente, headers, fila, estado="asistio", **datos):
    return cliente.post(
        "/asistencias/horas",
        headers=headers,
        json={
            "docente_id": fila["docente_id"],
            "fecha": fila["fecha"],
            "bloque_id": fila["bloque_id"],
            "programado_inicio": fila["programado_inicio"],
            "estado": estado,
            **datos,
        },
    )


def test_cada_hora_es_independiente_y_pendiente_no_es_falta(cliente, como_admin, escuela_horas):
    d = ver(cliente, como_admin)
    assert [(f["programado_inicio"], f["programado_fin"]) for f in d["filas"]] == [
        ("07:00:00", "08:00:00"),
        ("08:00:00", "09:00:00"),
        ("09:00:00", "10:00:00"),
    ]
    assert all(f["asistencia"] is None and f["estado"] == "pendiente" for f in d["filas"])
    assert d["totales"]["minutos"] == {
        "programadas": 180,
        "exigibles": 180,
        "cumplidas": 0,
        "faltantes": 0,
        "justificadas": 0,
        "pendientes": 180,
        "suspendidas": 0,
    }
    clases = ver(cliente, como_admin, tipo_actividad="materia")
    assert len(clases["filas"]) == 2 and clases["totales"]["horas"]["programadas"] == 2


def test_asiste_una_hora_y_falta_otra_del_mismo_dia(cliente, como_admin, escuela_horas):
    filas = ver(cliente, como_admin)["filas"]
    a = capturar(cliente, como_admin, filas[0])
    b = capturar(cliente, como_admin, filas[1], "falto")
    assert a.status_code == b.status_code == 201
    assert a.json()["id"] != b.json()["id"]
    d = ver(cliente, como_admin)
    assert [f["estado"] for f in d["filas"]] == ["asistio", "falto", "pendiente"]
    assert d["totales"]["horas"]["cumplidas"] == 1
    assert d["totales"]["horas"]["faltantes"] == 1
    assert d["totales"]["horas"]["pendientes"] == 1


def test_parciales_y_justificaciones_en_minutos_exactos(cliente, como_admin, escuela_horas):
    f = ver(cliente, como_admin)["filas"][0]
    r = capturar(
        cliente,
        como_admin,
        f,
        "parcial",
        hora_entrada="07:10",
        hora_salida="07:40",
        minutos_justificados=20,
        justificacion="Permiso ficticio parcial",
    )
    assert r.status_code == 201, r.text
    assert r.json()["minutos_cumplidos"] == 30 and r.json()["minutos_justificados"] == 20
    m = ver(cliente, como_admin)["totales"]["minutos"]
    assert (m["cumplidas"], m["faltantes"], m["justificadas"], m["pendientes"]) == (30, 10, 20, 120)
    assert (
        m["programadas"]
        == m["cumplidas"] + m["faltantes"] + m["justificadas"] + m["pendientes"] + m["suspendidas"]
    )


def test_retardo_no_acredita_minutos_no_cumplidos(cliente, como_admin, escuela_horas):
    f = ver(cliente, como_admin)["filas"][0]
    r = capturar(cliente, como_admin, f, "retardo", hora_entrada="07:15")
    assert r.status_code == 201 and r.json()["minutos_cumplidos"] == 45
    f = ver(cliente, como_admin)["filas"][0]
    assert f["estado"] == "retardo" and f["minutos"]["faltantes"] == 15
    assert f["tolerancia_minutos"] == 10


@pytest.mark.parametrize(
    "datos",
    [
        {"estado": "parcial"},
        {"estado": "parcial", "hora_entrada": "07:00", "hora_salida": "08:00"},
        {"estado": "parcial", "hora_entrada": "06:59", "hora_salida": "07:30"},
        {"estado": "parcial", "hora_entrada": "07:30", "hora_salida": "08:01"},
        {"estado": "parcial", "hora_entrada": "07:30", "hora_salida": "07:30"},
        {
            "estado": "parcial",
            "hora_entrada": "07:10",
            "hora_salida": "07:50",
            "minutos_justificados": 30,
            "justificacion": "Ficticio",
        },
        {
            "estado": "parcial",
            "hora_entrada": "07:10",
            "hora_salida": "07:50",
            "minutos_justificados": 10,
        },
        {"estado": "asistio", "hora_entrada": "07:15"},
        {"estado": "retardo"},
        {"estado": "retardo", "hora_entrada": "07:00"},
        {"estado": "falto", "hora_entrada": "07:10"},
        {"estado": "justificado"},
        {"estado": "justificado", "justificacion": "Ficticio", "hora_salida": "08:00"},
        {"estado": "justificado", "justificacion": "Ficticio", "minutos_justificados": 10},
        {"estado": "parcial", "hora_entrada": "07:10:30", "hora_salida": "07:50"},
        {"estado": "retardo", "hora_entrada": "07:10+01:00"},
        {"estado": "asistio", "minutos_cumplidos": 60},
    ],
)
def test_datos_invalidos_no_crean_registros(cliente, como_admin, escuela_horas, sesion, datos):
    f = ver(cliente, como_admin)["filas"][0]
    r = capturar(cliente, como_admin, f, **datos)
    assert r.status_code == 422, r.text
    assert sesion.scalar(select(AsistenciaHora.id)) is None


def test_duplicados_rechazados_en_api_y_base(cliente, como_admin, escuela_horas, sesion):
    f = ver(cliente, como_admin)["filas"][0]
    r = capturar(cliente, como_admin, f)
    assert r.status_code == 201
    assert capturar(cliente, como_admin, f, "falto").status_code == 409
    a = sesion.get(AsistenciaHora, r.json()["id"])
    copia = {
        c.name: getattr(a, c.name)
        for c in a.__table__.columns
        if c.name not in ("id", "creado_en", "actualizado_en")
    }
    with pytest.raises(IntegrityError), sesion.begin_nested():
        sesion.add(AsistenciaHora(**copia))
        sesion.flush()


def test_dos_capturas_concurrentes_solo_crean_una(cliente, como_admin, escuela_horas):
    f = ver(cliente, como_admin)["filas"][0]

    def guardar(_):
        with TestClient(app) as c:
            return capturar(c, como_admin, f).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(guardar, range(2))) == [201, 409]


@pytest.fixture
def capturista_horas(cliente, sesion):
    permisos = list(
        sesion.scalars(
            select(Permiso).where(Permiso.clave.in_(["asistencia.ver", "asistencia.registrar"]))
        )
    )
    rol = sesion.scalar(select(Rol).where(Rol.nombre == "capturista_horas_ficticio"))
    if rol is None:
        rol = Rol(nombre="capturista_horas_ficticio", descripcion="Ficticio", permisos=permisos)
        sesion.add(rol)
        sesion.commit()
    crear_usuario(sesion, "horas@prueba.mx", "Captura Ficticia", rol.nombre, "clave-ficticia-larga")
    token = cliente.post(
        "/auth/login", data={"username": "horas@prueba.mx", "password": "clave-ficticia-larga"}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_correcciones_con_permiso_motivo_e_historial(
    cliente, como_admin, capturista_horas, escuela_horas
):
    f = ver(cliente, como_admin)["filas"][0]
    a = capturar(cliente, como_admin, f).json()
    ruta = f"/asistencias/horas/{a['id']}"
    assert cliente.patch(ruta, headers=como_admin, json={"estado": "falto"}).status_code == 422
    datos = {"estado": "falto", "motivo": "Corrección ficticia de la hora"}
    assert cliente.patch(ruta, headers=capturista_horas, json=datos).status_code == 403
    r = cliente.patch(ruta, headers=como_admin, json=datos)
    assert r.status_code == 200 and r.json()["correcciones"] == 1
    assert r.json()["minutos_cumplidos"] == 0
    cambios = get(cliente, como_admin, ruta + "/historial")
    assert [c["accion"] for c in cambios] == ["registrar", "corregir"]
    assert cambios[1]["antes"]["minutos_cumplidos"] == 60
    assert cambios[1]["despues"]["motivo"] == datos["motivo"]
    assert cambios[0]["despues"]["horario_id"] == escuela_horas["horario"]
    assert cliente.patch(ruta, headers=como_admin, json=datos).status_code == 422


def test_correccion_del_dia_y_justificacion_futura(
    cliente, como_admin, capturista_horas, escuela_horas
):
    f = ver(cliente, como_admin, "2026-11-04")["filas"][0]
    a = capturar(cliente, capturista_horas, f).json()
    r = cliente.patch(
        f"/asistencias/horas/{a['id']}",
        headers=capturista_horas,
        json={"estado": "falto", "motivo": "Corrección ficticia del día"},
    )
    assert r.status_code == 200
    f = ver(cliente, como_admin, "2026-11-09")["filas"][0]
    assert capturar(cliente, como_admin, f).status_code == 422
    r = capturar(cliente, como_admin, f, "justificado", justificacion="Permiso futuro ficticio")
    assert r.status_code == 201 and r.json()["minutos_justificados"] == 60
    assert (
        cliente.patch(
            f"/asistencias/horas/{r.json()['id']}",
            headers=como_admin,
            json={"estado": "asistio", "motivo": "No debe acreditar futuro"},
        ).status_code
        == 422
    )


def test_suspension_no_genera_faltas_y_excepcion_autorizada(
    cliente, como_admin, capturista_horas, escuela_horas
):
    cliente.post(
        "/calendario",
        headers=como_admin,
        json={
            "tipo": "suspension",
            "fecha_inicio": LUNES,
            "fecha_fin": LUNES,
            "turno": "matutino",
            "descripcion": "Suspensión ficticia",
        },
    )
    d = ver(cliente, como_admin)
    assert all(f["estado"] == "inhabil" for f in d["filas"])
    assert d["totales"]["minutos"]["suspendidas"] == 180
    assert d["totales"]["minutos"]["faltantes"] == d["totales"]["minutos"]["exigibles"] == 0
    f = d["filas"][0]
    assert capturar(cliente, como_admin, f).status_code == 409
    assert capturar(cliente, capturista_horas, f, autorizar_dia_inhabil=True).status_code == 403
    assert capturar(cliente, como_admin, f, autorizar_dia_inhabil=True).status_code == 201
    assert ver(cliente, como_admin)["totales"]["minutos"]["cumplidas"] == 60


def test_no_convierte_registros_por_turno(cliente, como_admin, escuela_horas, sesion):
    r = cliente.post(
        "/asistencias",
        headers=como_admin,
        json={
            "docente_id": escuela_horas["docente"],
            "fecha": LUNES,
            "turno": "matutino",
            "estado": "asistio",
        },
    )
    assert r.status_code == 201
    d = ver(cliente, como_admin)
    assert d["registros_por_turno_sin_convertir"] == [r.json()["id"]]
    assert all(f["asistencia"] is None for f in d["filas"])
    assert d["totales"]["minutos"]["cumplidas"] == 0
    assert sesion.scalar(select(Asistencia.id)) == r.json()["id"]


def test_versiones_por_fecha_y_capturas_fuera_del_programa(
    cliente, como_admin, escuela_horas, sesion
):
    e = escuela_horas
    f = ver(cliente, como_admin, "2026-11-04")["filas"][0]
    a = capturar(cliente, como_admin, f).json()
    v2 = nuevo_borrador(cliente, como_admin, e, basado_en_id=e["horario"])
    cliente.put(
        f"/horarios/{v2['id']}/bloques",
        headers=como_admin,
        json=[
            {
                "dia": "miercoles",
                "hora_inicio": "10:00",
                "hora_fin": "11:00",
                "asignatura_id": e["fisica"],
                "grupo_id": e["grupo_a"],
                "aula_id": e["m02"],
            }
        ],
    )
    assert (
        cliente.post(
            f"/horarios/{v2['id']}/confirmar",
            headers=como_admin,
            json={"vigente_desde": "2026-11-03"},
        ).status_code
        == 200
    )
    assert ver(cliente, como_admin)["filas"][0]["horario_id"] == e["horario"]
    d = ver(cliente, como_admin, "2026-11-04")
    assert len(d["filas"]) == 1 and d["filas"][0]["horario_id"] == v2["id"]
    assert d["totales"]["minutos"]["cumplidas"] == 0
    assert d["totales_fuera_de_programacion"]["minutos"]["cumplidas"] == 60
    viejo = d["registros_fuera_de_programacion"][0]
    assert viejo["asistencia"]["id"] == a["id"] and viejo["aula"] == "M01"
    assert sesion.get(AsistenciaHora, a["id"]).horario_id == e["horario"]


def test_cambio_de_programa_no_permite_duplicar_tramos_solapados(
    cliente, como_admin, escuela_horas
):
    e = escuela_horas
    f = ver(cliente, como_admin, "2026-11-04")["filas"][0]
    capturar(cliente, como_admin, f)
    v2 = nuevo_borrador(cliente, como_admin, e, basado_en_id=e["horario"])
    cliente.put(
        f"/horarios/{v2['id']}/bloques",
        headers=como_admin,
        json=[
            {
                "dia": "miercoles",
                "hora_inicio": "07:30",
                "hora_fin": "08:30",
                "asignatura_id": e["fisica"],
                "grupo_id": e["grupo_a"],
            }
        ],
    )
    cliente.post(
        f"/horarios/{v2['id']}/confirmar", headers=como_admin, json={"vigente_desde": "2026-11-03"}
    )
    d = ver(cliente, como_admin, "2026-11-04")
    assert d["filas"][0]["bloqueada_por_registro_previo"]
    assert capturar(cliente, como_admin, d["filas"][0]).status_code == 409


def test_vigencia_desconocida_no_genera_horas_y_conserva_captura(
    cliente, como_admin, escuela_horas, sesion
):
    f = ver(cliente, como_admin)["filas"][0]
    capturar(cliente, como_admin, f)
    h = sesion.get(Horario, escuela_horas["horario"])
    h.vigencia_confirmada, h.vigente_desde = False, None
    sesion.commit()
    d = ver(cliente, como_admin)
    assert d["filas"] == [] and len(d["registros_fuera_de_programacion"]) == 1
    assert d["totales"]["minutos"]["programadas"] == 0
    assert capturar(cliente, como_admin, f).status_code == 422


def test_fracciones_no_se_redondean_y_cambio_de_turno(cliente, como_admin, escuela_horas):
    e = escuela_horas
    h = nuevo_borrador(cliente, como_admin, e, docente="docente2")
    cliente.put(
        f"/horarios/{h['id']}/bloques",
        headers=como_admin,
        json=[
            {
                "dia": "lunes",
                "hora_inicio": "13:30",
                "hora_fin": "15:00",
                "asignatura_id": e["fisica"],
                "grupo_id": e["grupo_a"],
                "aula_id": e["m02"],
            }
        ],
    )
    cliente.post(
        f"/horarios/{h['id']}/confirmar",
        headers=como_admin,
        json={"vigente_desde": "2026-08-01", "aceptar_advertencias": True},
    )
    d = ver(cliente, como_admin, docente_id=e["docente2"])
    assert [(f["programado_inicio"], f["programado_fin"], f["turno"]) for f in d["filas"]] == [
        ("13:30:00", "14:30:00", "matutino"),
        ("14:30:00", "15:00:00", "vespertino"),
    ]
    assert d["totales"]["horas"]["programadas"] == 1.5


def test_permisos_y_periodo_cerrado(cliente, como_admin, como_consulta, escuela_horas):
    f = ver(cliente, como_consulta)["filas"][0]
    assert capturar(cliente, como_consulta, f).status_code == 403
    assert cliente.get("/bitacora/horas", params={"fecha": LUNES}).status_code == 401
    assert (
        cliente.get(
            "/bitacora/horas/exportar", headers=como_consulta, params={"fecha": LUNES}
        ).status_code
        == 403
    )
    a = capturar(cliente, como_admin, f).json()
    cliente.post(f"/periodos/{escuela_horas['periodo']}/cerrar", headers=como_admin)
    assert capturar(cliente, como_admin, ver(cliente, como_admin)["filas"][1]).status_code == 409
    assert (
        cliente.patch(
            f"/asistencias/horas/{a['id']}",
            headers=como_admin,
            json={"estado": "falto", "motivo": "No modificar cerrado"},
        ).status_code
        == 409
    )


def test_reportes_pdf_excel_calculan_horas_y_mantienen_firmas(cliente, como_admin, escuela_horas):
    filas = ver(cliente, como_admin)["filas"]
    capturar(cliente, como_admin, filas[0])
    capturar(cliente, como_admin, filas[1], "falto")
    capturar(
        cliente,
        como_admin,
        filas[2],
        "parcial",
        hora_entrada="09:00",
        hora_salida="09:30",
        minutos_justificados=30,
        justificacion="Permiso ficticio",
    )
    params = {"desde": LUNES, "hasta": LUNES, "formato": "xlsx"}
    r = cliente.get("/bitacora/horas/reporte", headers=como_admin, params=params)
    assert r.status_code == 200, r.text
    libro = load_workbook(io.BytesIO(r.content))
    resumen = {f[0]: f[1:] for f in libro["Resumen de horas"].iter_rows(values_only=True)}
    assert resumen["Programadas"] == (180, 3)
    assert resumen["Cumplidas"] == (90, 1.5)
    assert resumen["Faltantes"] == (60, 1)
    assert resumen["Justificadas"] == (30, 0.5)
    assert resumen["Pendientes"] == (0, 0)
    assert "Por docente" in libro.sheetnames and "Fuera de programación" in libro.sheetnames
    r = cliente.get(
        "/bitacora/horas/reporte", headers=como_admin, params={**params, "formato": "pdf"}
    )
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    with pymupdf.open(stream=r.content, filetype="pdf") as pdf:
        texto = "".join(p.get_text() for p in pdf)
    assert "Cumplidas" in texto and "Justificadas" in texto
    assert "Asistente de Jefatura" in texto and "Jefatura de Electromecánica" in texto


def test_filtros_rango_y_fechas_sin_clase(cliente, como_admin, escuela_horas):
    assert ver(cliente, como_admin, "2026-11-08")["filas"] == []
    assert ver(cliente, como_admin, "2027-01-04")["filas"] == []
    assert ver(cliente, como_admin, turno="vespertino")["filas"] == []
    assert len(ver(cliente, como_admin, docente_id=escuela_horas["docente"])["filas"]) == 3
    assert (
        cliente.get(
            "/bitacora/horas/reporte",
            headers=como_admin,
            params={"desde": LUNES, "hasta": "2027-03-01"},
        ).status_code
        == 422
    )


def test_migracion_aditiva_no_convierte_ni_modifica_registros(base_de_datos):
    with base_de_datos.connect() as c:
        transaccion = c.begin()
        try:
            c.execute(text("CREATE SCHEMA prueba_migracion_horas"))
            c.execute(text("SET LOCAL search_path TO prueba_migracion_horas"))
            cfg = Config("server/alembic.ini")
            cfg.attributes["connection"] = c
            command.upgrade(cfg, "e5a001")
            c.execute(
                text(
                    "INSERT INTO docente (id,nombre,nombre_normalizado,activo) "
                    "VALUES (1,'FICTICIO','FICTICIO',true)"
                )
            )
            c.execute(
                text(
                    "INSERT INTO periodo (id,nombre,fecha_inicio,fecha_fin,estado) "
                    "VALUES (1,'FICTICIO','2026-08-01','2026-12-31','activo')"
                )
            )
            c.execute(
                text(
                    "INSERT INTO horario (id,docente_id,periodo_id,version,estado,origen,notas,"
                    "vigente_desde,vigencia_confirmada) VALUES "
                    "(1,1,1,1,'vigente','manual','','2026-08-17',true)"
                )
            )
            c.execute(
                text(
                    "INSERT INTO asistencia (docente_id,fecha,turno,estado,observaciones,"
                    "justificacion,horario_id,programado_inicio,programado_fin,"
                    "en_dia_inhabil,correcciones) VALUES "
                    "(1,'2026-11-02','matutino','asistio','','',1,'07:00','09:00',false,0)"
                )
            )
            c.execute(
                text(
                    "INSERT INTO auditoria (accion,entidad,entidad_id,despues) "
                    "VALUES ('registrar','asistencia','1','{}')"
                )
            )
            anterior = c.execute(text("SELECT row_to_json(a) FROM asistencia a")).scalar()
            vigencia = c.execute(text("SELECT row_to_json(h) FROM horario h")).scalar()
            command.upgrade(cfg, "head")
            assert c.execute(text("SELECT row_to_json(a) FROM asistencia a")).scalar() == anterior
            assert c.execute(text("SELECT row_to_json(h) FROM horario h")).scalar() == vigencia
            assert c.execute(text("SELECT count(*) FROM asistencia_hora")).scalar() == 0
            assert c.execute(text("SELECT count(*) FROM auditoria")).scalar() == 1
        finally:
            transaccion.rollback()


def test_correccion_de_parcial_no_arrastra_intervalo_anterior(cliente, como_admin, escuela_horas):
    f = ver(cliente, como_admin)["filas"][0]
    a = capturar(
        cliente,
        como_admin,
        f,
        "parcial",
        hora_entrada="07:10",
        hora_salida="07:40",
        minutos_justificados=10,
        justificacion="Permiso ficticio",
    ).json()
    r = cliente.patch(
        f"/asistencias/horas/{a['id']}",
        headers=como_admin,
        json={"estado": "falto", "motivo": "Corrección ficticia del estado"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["hora_entrada"] is None and r.json()["minutos_justificados"] == 0
    cambios = get(cliente, como_admin, f"/asistencias/horas/{a['id']}/historial")
    assert cambios[-1]["antes"]["minutos_cumplidos"] == 30
    assert cambios[-1]["despues"]["minutos_cumplidos"] == 0


def test_reportes_advierten_fechas_desconocidas_y_no_ejecutan_formulas(
    cliente, como_admin, escuela_horas, sesion
):
    e = escuela_horas
    cliente.patch(f"/docentes/{e['docente']}", headers=como_admin, json={"nombre": "=1+2"})
    f = ver(cliente, como_admin)["filas"][0]
    capturar(cliente, como_admin, f)
    params = {"fecha": LUNES, "formato": "xlsx"}
    r = cliente.get("/bitacora/horas/exportar", headers=como_admin, params=params)
    assert r.status_code == 200
    celdas = [c for fila in load_workbook(io.BytesIO(r.content)).active for c in fila]
    assert any(c.value == "=1+2" and c.data_type == "s" for c in celdas)
    h = sesion.get(Horario, e["horario"])
    h.vigencia_confirmada, h.vigente_desde = False, None
    sesion.commit()
    r = cliente.get("/bitacora/horas/exportar", headers=como_admin, params=params)
    libro = load_workbook(io.BytesIO(r.content))
    assert any("vigencia desconocida" in str(c.value) for fila in libro.active for c in fila)
    assert any(c.value == "=1+2" for fila in libro["Fuera de programación"] for c in fila)


def test_hora_inventada_y_bloque_de_otro_docente_se_rechazan(cliente, como_admin, escuela_horas):
    f = ver(cliente, como_admin)["filas"][0]
    assert capturar(cliente, como_admin, {**f, "programado_inicio": "07:15"}).status_code == 422
    assert (
        capturar(cliente, como_admin, {**f, "docente_id": escuela_horas["docente2"]}).status_code
        == 422
    )
    assert capturar(cliente, como_admin, {**f, "bloque_id": 99999}).status_code == 422
