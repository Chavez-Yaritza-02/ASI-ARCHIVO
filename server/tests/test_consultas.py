"""Etapa 5 contra API y PostgreSQL: datos completamente ficticios."""

import io
from datetime import date

import pymupdf as fitz
import pytest
from openpyxl import load_workbook
from sqlalchemy import select

from app.cli import crear_usuario
from app.models import Auditoria, Horario, Permiso, Rol
from app.models.base import Base
from server.tests.test_horarios import nuevo_borrador

pytest_plugins = ["server.tests.test_horarios"]


@pytest.fixture
def escuela_consulta(cliente, como_admin, base, bloques_validos):
    h = nuevo_borrador(cliente, como_admin, base)
    assert (
        cliente.put(
            f"/horarios/{h['id']}/bloques", json=bloques_validos, headers=como_admin
        ).status_code
        == 200
    )
    r = cliente.post(
        f"/horarios/{h['id']}/confirmar", headers=como_admin, json={"vigente_desde": "2026-08-01"}
    )
    assert r.status_code == 200, r.text
    return {**base, "horario": h["id"]}


def get(cliente, headers, ruta, **params):
    r = cliente.get(ruta, params=params, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def test_buscar_nombre_acentos_catalogos_y_paginacion(cliente, como_admin, escuela_consulta):
    d = get(cliente, como_admin, "/buscador", texto="docente prueba", fecha="2026-11-02", limite=1)
    assert d["docentes"]["total"] == 2 and len(d["docentes"]["resultados"]) == 1
    otra = get(
        cliente,
        como_admin,
        "/buscador",
        texto="docente prueba",
        fecha="2026-11-02",
        limite=1,
        offset=1,
    )
    assert otra["docentes"]["resultados"][0]["id"] != d["docentes"]["resultados"][0]["id"]
    for texto, entidad in [("cálc", "materias"), ("IEM 3A", "grupos"), ("m01", "aulas")]:
        d = get(cliente, como_admin, "/buscador", texto=texto, fecha="2026-11-02")
        assert d[entidad]["total"] == 1
        assert d["actividades"]["total"] > 0
    assert get(cliente, como_admin, "/buscador", texto="' OR 1=1 --")["docentes"]["total"] == 0


@pytest.mark.parametrize(
    "cambio,esperado",
    [
        ({}, 1),
        ({"carrera": "OTRA"}, 0),
        ({"semestre": 7}, 0),
        ({"turno": "vespertino"}, 0),
        ({"dia": 1}, 0),
        ({"periodo_id": 999}, 0),
    ],
)
def test_filtros_busqueda(cliente, como_admin, escuela_consulta, cambio, esperado):
    filtros = {
        "carrera": "iem",
        "semestre": 3,
        "periodo_id": escuela_consulta["periodo"],
        "dia": 0,
        "turno": "matutino",
        **cambio,
    }
    d = get(cliente, como_admin, "/buscador", fecha="2026-11-02", **filtros)
    assert d["docentes"]["total"] == esperado
    assert d["materias"]["total"] == esperado
    assert d["grupos"]["total"] == esperado


def test_grupos_filtrados_no_asignan_letras_pendientes(cliente, como_admin, escuela_consulta):
    pendiente = cliente.post("/grupos", json={"letra": "A"}, headers=como_admin)
    assert pendiente.status_code == 201
    grupos = get(
        cliente,
        como_admin,
        "/consultas/grupos",
        carrera="iem",
        semestre=3,
        letra="a",
        periodo_id=escuela_consulta["periodo"],
    )
    assert [g["id"] for g in grupos] == [escuela_consulta["grupo_a"]]
    r = cliente.get(
        f"/consultas/grupos/{pendiente.json()['id']}/horario",
        params={"fecha": "2026-11-02"},
        headers=como_admin,
    )
    assert r.status_code == 409


def semanal(cliente, headers, grupo, fecha="2026-11-02"):
    return get(cliente, headers, f"/consultas/grupos/{grupo}/horario", fecha=fecha)


def test_semana_con_version_distinta_a_mitad_de_semana(cliente, como_admin, escuela_consulta):
    e = escuela_consulta
    v2 = nuevo_borrador(cliente, como_admin, e, basado_en_id=e["horario"])
    bloques = [
        {
            "dia": "miercoles",
            "hora_inicio": "10:00",
            "hora_fin": "11:00",
            "asignatura_id": e["fisica"],
            "grupo_id": e["grupo_a"],
            "aula_id": e["m02"],
        }
    ]
    cliente.put(f"/horarios/{v2['id']}/bloques", json=bloques, headers=como_admin)
    r = cliente.post(
        f"/horarios/{v2['id']}/confirmar", headers=como_admin, json={"vigente_desde": "2026-11-03"}
    )
    assert r.status_code == 200
    d = semanal(cliente, como_admin, e["grupo_a"])
    assert [(b["fecha"], b["version"], b["aula"]) for b in d["bloques"]] == [
        ("2026-11-02", 1, "M01"),
        ("2026-11-04", 2, "M02"),
    ]
    assert d["desde"] == "2026-11-02" and d["hasta"] == "2026-11-08"
    assert semanal(cliente, como_admin, e["grupo_a"], "2027-01-05")["bloques"] == []


def test_traslape_grupo_entre_docentes(cliente, como_admin, escuela_consulta):
    e = escuela_consulta
    h = nuevo_borrador(cliente, como_admin, e, docente="docente2")
    cliente.put(
        f"/horarios/{h['id']}/bloques",
        headers=como_admin,
        json=[
            {
                "dia": "lunes",
                "hora_inicio": "08:00",
                "hora_fin": "10:00",
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
    datos = semanal(cliente, como_admin, e["grupo_a"])
    assert sum(bool(b["conflictos"]) for b in datos["bloques"]) == 2


def ubicacion(cliente, headers, docente, hora="07:30", fecha="2026-11-02"):
    return get(cliente, headers, f"/consultas/docentes/{docente}/ubicacion", fecha=fecha, hora=hora)


def test_ubicacion_es_programada_intervalos_y_sin_clase(cliente, como_consulta, escuela_consulta):
    e = escuela_consulta
    datos = ubicacion(cliente, como_consulta, e["docente"])
    assert datos["tipo"] == "ubicacion_programada" and datos["ubicacion_real"] is None
    assert datos["bloques"][0]["aula_programada"] == "M01"
    assert "no confirma presencia física" in datos["aviso"]
    assert ubicacion(cliente, como_consulta, e["docente"], "07:00")["bloques"]
    assert (
        ubicacion(cliente, como_consulta, e["docente"], "10:00")["estado"] == "sin_clase_asignada"
    )
    assert ubicacion(cliente, como_consulta, e["docente"], fecha="2026-11-08")["bloques"] == []
    assert ubicacion(cliente, como_consulta, e["docente"], fecha="2027-01-04")["bloques"] == []


def test_ubicacion_suspension_y_cambio_aula_sin_inferencias(cliente, como_admin, escuela_consulta):
    e = escuela_consulta
    incidencia = cliente.post(
        "/incidencias",
        headers=como_admin,
        json={
            "fecha": "2026-11-02",
            "docente_id": e["docente"],
            "tipo": "cambio_aula",
            "turno": "matutino",
            "descripcion": "Cambio a aula ficticia, por verificar",
        },
    ).json()
    d = ubicacion(cliente, como_admin, e["docente"])
    assert d["bloques"][0]["estado"] == "requiere_verificacion"
    assert d["bloques"][0]["aula_programada"] is None
    assert d["bloques"][0]["aula"] == "M01"  # aula base, no sustituida por texto libre
    cliente.post(f"/incidencias/{incidencia['id']}/anular", headers=como_admin)
    assert ubicacion(cliente, como_admin, e["docente"])["bloques"][0]["estado"] == "programada"
    cliente.post(
        "/calendario",
        headers=como_admin,
        json={
            "tipo": "suspension",
            "fecha_inicio": "2026-11-02",
            "fecha_fin": "2026-11-02",
            "turno": "matutino",
            "descripcion": "Suspensión ficticia",
        },
    )
    d = ubicacion(cliente, como_admin, e["docente"])
    assert d["bloques"][0]["estado"] == "suspendida"
    assert d["bloques"][0]["aula_programada"] is None
    assert not semanal(cliente, como_admin, e["grupo_a"])["bloques"][0]["habil"]


def test_incidencia_general_permiso_y_turno(cliente, como_admin, escuela_consulta):
    e = escuela_consulta
    cliente.post(
        "/incidencias",
        headers=como_admin,
        json={
            "fecha": "2026-11-02",
            "tipo": "permiso",
            "turno": "vespertino",
            "descripcion": "Permiso ficticio del turno vespertino",
        },
    )
    assert ubicacion(cliente, como_admin, e["docente"])["bloques"][0]["estado"] == "programada"
    cliente.post(
        "/incidencias",
        headers=como_admin,
        json={
            "fecha": "2026-11-02",
            "tipo": "otra",
            "descripcion": "Incidencia general ficticia",
        },
    )
    d = ubicacion(cliente, como_admin, e["docente"])
    assert d["bloques"][0]["estado"] == "requiere_verificacion"
    assert len(d["bloques"][0]["incidencias"]) == 1


def test_vigencia_desconocida_se_excluye_y_se_advierte(
    cliente, como_admin, escuela_consulta, sesion
):
    e = escuela_consulta
    h = sesion.get(Horario, e["horario"])
    h.vigencia_confirmada, h.vigente_desde = False, None
    sesion.commit()
    d = ubicacion(cliente, como_admin, e["docente"])
    assert d["estado"] == "vigencia_desconocida" and d["bloques"] == []
    assert d["horarios_sin_vigencia_confirmada"] == [h.id]
    d = semanal(cliente, como_admin, e["grupo_a"])
    assert d["bloques"] == [] and d["horarios_sin_vigencia_confirmada"] == [h.id]
    assert (
        get(cliente, como_admin, "/buscador", fecha="2026-11-02", dia=0)["actividades"]["total"]
        == 0
    )


def test_exportar_grupo_pdf_excel_y_permisos(cliente, como_admin, como_consulta, escuela_consulta):
    ruta = f"/consultas/grupos/{escuela_consulta['grupo_a']}/exportar"
    params = {"fecha": "2026-11-02"}
    r = cliente.get(ruta, params=params, headers=como_admin)
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    with fitz.open(stream=r.content, filetype="pdf") as pdf:
        texto = "".join(p.get_text() for p in pdf)
    assert "Horario semanal" in texto and "Asistente de Jefatura" in texto
    assert "Jefatura de Electromecánica" in texto
    r = cliente.get(ruta, params={**params, "formato": "xlsx"}, headers=como_admin)
    libro = load_workbook(io.BytesIO(r.content))
    textos = [str(c.value) for fila in libro.active for c in fila if c.value is not None]
    assert "DOCENTE PRUEBA UNO" in textos and "07:00" in textos
    assert cliente.get(ruta, params=params, headers=como_consulta).status_code == 403
    assert cliente.get(ruta, params=params).status_code == 401


def test_excel_no_ejecuta_formulas(cliente, como_admin, escuela_consulta):
    e = escuela_consulta
    cliente.patch(f"/docentes/{e['docente']}", headers=como_admin, json={"nombre": "=1+2"})
    r = cliente.get(
        f"/consultas/grupos/{e['grupo_a']}/exportar",
        headers=como_admin,
        params={"fecha": "2026-11-02", "formato": "xlsx"},
    )
    celdas = [c for fila in load_workbook(io.BytesIO(r.content)).active for c in fila]
    assert any(c.value == "=1+2" and c.data_type == "s" for c in celdas)


def test_tolerancia_administrativa_validada_auditada_y_aplicada(
    cliente, como_admin, como_consulta, escuela_consulta, sesion
):
    assert get(cliente, como_consulta, "/configuracion/asistencia")["tolerancia_minutos"] == 10
    assert (
        cliente.put(
            "/configuracion/asistencia", headers=como_consulta, json={"tolerancia_minutos": 15}
        ).status_code
        == 403
    )
    assert (
        cliente.put(
            "/configuracion/asistencia", headers=como_admin, json={"tolerancia_minutos": -1}
        ).status_code
        == 422
    )
    assert (
        cliente.put(
            "/configuracion/asistencia", headers=como_admin, json={"tolerancia_minutos": 15}
        ).status_code
        == 200
    )
    assert (
        get(cliente, como_consulta, "/bitacora", fecha="2026-11-02")["filas"][0][
            "tolerancia_minutos"
        ]
        == 15
    )
    a = sesion.scalar(select(Auditoria).where(Auditoria.accion == "configurar"))
    assert a.antes["tolerancia_minutos"] == 10 and a.despues["tolerancia_minutos"] == 15


def test_permisos_parciales_no_revelan_horarios(cliente, sesion, escuela_consulta):
    permiso = sesion.scalar(select(Permiso).where(Permiso.clave == "docentes.ver"))
    rol = Rol(nombre="solo_docentes_ficticio", descripcion="Ficticio", permisos=[permiso])
    sesion.add(rol)
    sesion.commit()
    crear_usuario(
        sesion, "parcial@prueba.mx", "Parcial Ficticio", rol.nombre, "clave-ficticia-larga"
    )
    token = cliente.post(
        "/auth/login", data={"username": "parcial@prueba.mx", "password": "clave-ficticia-larga"}
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    d = get(cliente, headers, "/buscador", texto="PRUEBA")
    assert d["docentes"]["total"] == 2 and d["actividades"]["total"] == 0
    assert d["materias"]["total"] == 0
    assert cliente.get("/buscador", params={"dia": 0}, headers=headers).status_code == 403
    assert cliente.get("/consultas/grupos", headers=headers).status_code == 403
    assert (
        cliente.get(
            f"/consultas/docentes/{escuela_consulta['docente']}/ubicacion", headers=headers
        ).status_code
        == 403
    )


def test_validacion_filtros_y_reloj(cliente, como_admin):
    for params in (
        {"dia": 6},
        {"semestre": 0},
        {"turno": "noche"},
        {"limite": 1000},
        {"offset": -1},
    ):
        assert cliente.get("/buscador", params=params, headers=como_admin).status_code == 422
    d = get(cliente, como_admin, "/consultas/ahora")
    assert d["zona"] == "America/Mexico_City"
    date.fromisoformat(d["fecha"])


def test_modelos_y_migraciones_coinciden(base_de_datos):
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    with base_de_datos.connect() as c:
        assert compare_metadata(MigrationContext.configure(c), Base.metadata) == []
