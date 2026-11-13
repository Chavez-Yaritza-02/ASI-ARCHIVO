"""Importación de faltas y salidas anticipadas desde Excel. Solo datos ficticios.

Corre igual en PostgreSQL y en SQLite (aplicación local).
"""

import io
from datetime import date, datetime, time

import pytest
from openpyxl import Workbook, load_workbook
from sqlalchemy import func, select

from app.importers import incidencias_excel as lector
from app.models import AsistenciaHora, Auditoria, ImportacionIncidencias, IncidenciaImportada
from app.services import asistencia_hora as servicio_horas
from app.services import incidencias_excel as servicio
from app.services.comun import ErrorNegocio

HOY = date(2026, 11, 12)
OMEGA, ALFA, BETA = "PRUEBA LARA OMEGA ERNESTO", "DOCENTE FICTICIO ALFA", "DOCENTE FICTICIO BETA"
FILAS = [
    # Caso especial (ficticio): salió a las 19:00, una hora antes de terminar su jornada.
    [
        datetime(2026, 10, 9),
        "Lara Omega Ernesto Prueba",
        "SALIDA ANTICIPADA",
        "Salió a las 7:00 p. m., una hora antes",
    ],
    ["08/10/2026", ALFA, "FALTA", ""],
    ["08/10/2026", "Docente Ficticio Alfa", "Falta", ""],  # repetida
    ["35/10/2026", BETA, "FALTA", ""],  # fecha imposible
    ["2026-10-07", "DOCENTE INEXISTENTE ZETA", "FALTA", ""],  # no está en el catálogo
]


def excel(filas=FILAS, encabezado=("FECHA", "NOMBRE DEL DOCENTE", "INCIDENCIA", "OBSERVACIONES")):
    libro = Workbook()
    hoja = libro.active
    hoja.title = "Incidencias"
    hoja.append(["REPORTE FICTICIO DE INCIDENCIAS"])
    hoja.append(list(encabezado))
    for f in filas:
        hoja.append(f)
    salida = io.BytesIO()
    libro.save(salida)
    return salida.getvalue()


@pytest.fixture
def escuela(cliente, como_admin, monkeypatch):
    monkeypatch.setattr(servicio_horas, "hoy", lambda: HOY)
    monkeypatch.setattr(servicio, "hoy", lambda: HOY)

    def crear(ruta, datos):
        r = cliente.post(ruta, json=datos, headers=como_admin)
        assert r.status_code == 201, r.text
        return r.json()["id"]

    periodo = crear(
        "/periodos",
        {
            "nombre": "Agosto - Diciembre 2026",
            "fecha_inicio": "2026-08-01",
            "fecha_fin": "2026-12-31",
        },
    )
    assert cliente.post(f"/periodos/{periodo}/activar", headers=como_admin).status_code == 200
    materia = crear("/asignaturas", {"nombre": "CÁLC. DIF."})
    aula = crear("/aulas", {"clave": "M01"})
    grupo = crear("/grupos", {"letra": "A", "periodo_id": periodo, "carrera": "IEM", "semestre": 3})
    docentes = {}
    for nombre, (dia, inicio, fin) in {
        OMEGA: ("viernes", "17:00", "20:00"),
        ALFA: ("jueves", "07:00", "09:00"),
        BETA: ("miercoles", "07:00", "08:00"),
    }.items():
        docentes[nombre] = crear("/docentes", {"nombre": nombre})
        h = crear("/horarios", {"docente_id": docentes[nombre], "periodo_id": periodo})
        bloque = {"dia": dia, "hora_inicio": inicio, "hora_fin": fin, "asignatura_id": materia}
        bloque |= {"grupo_id": grupo, "aula_id": aula}
        assert cliente.put(f"/horarios/{h}/bloques", json=[bloque], headers=como_admin).is_success
        r = cliente.post(
            f"/horarios/{h}/confirmar",
            json={"vigente_desde": "2026-08-17", "aceptar_advertencias": True},
            headers=como_admin,
        )
        assert r.status_code == 200, r.text
    return {"periodo": periodo, "docentes": docentes}


def subir(cliente, headers, contenido=None, nombre="incidencias-ficticias.xlsx"):
    return cliente.post(
        "/incidencias-excel",
        headers=headers,
        files={
            "archivo": (
                nombre,
                contenido if contenido is not None else excel(),
                "application/octet-stream",
            )
        },
    )


def cargar(cliente, headers):
    r = subir(cliente, headers)
    assert r.status_code == 201, r.text
    return r.json()


def fila(datos, numero_en_lista):
    return datos["filas"][numero_en_lista]


def editar(cliente, headers, fila_id, **cambios):
    r = cliente.patch(f"/incidencias-excel/filas/{fila_id}", json=cambios, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def horas(cliente, headers, fila_id):
    r = cliente.get(f"/incidencias-excel/filas/{fila_id}/horas", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["horas"]


def elegir(cliente, headers, fila_id, *inicios):
    disponibles = horas(cliente, headers, fila_id)
    elegidas = [
        {"bloque_id": h["bloque_id"], "programado_inicio": h["programado_inicio"]}
        for h in disponibles
        if h["programado_inicio"][:5] in inicios
    ]
    assert len(elegidas) == len(inicios)
    return editar(cliente, headers, fila_id, horas=elegidas)


def importar(cliente, headers, importacion_id, *fila_ids):
    return cliente.post(
        f"/incidencias-excel/{importacion_id}/importar",
        json={"filas": list(fila_ids)},
        headers=headers,
    )


def registros(sesion):
    sesion.expire_all()
    return sesion.scalars(select(AsistenciaHora).order_by(AsistenciaHora.programado_inicio)).all()


# --- lectura y vista previa -----------------------------------------------------------


def test_leer_el_excel_no_registra_asistencia_y_detecta_problemas(
    cliente, como_admin, escuela, sesion
):
    d = cargar(cliente, como_admin)
    assert d["total_filas"] == 5 and d["pendientes"] == 5 and d["listas"] == 0
    assert registros(sesion) == []
    salida, falta, repetida, mala, nadie = d["filas"]
    assert salida["docente"]["id"] == escuela["docentes"][OMEGA]  # orden distinto de palabras
    assert salida["docente_estado"] == "coincide"
    assert (salida["fecha"], salida["tipo"], salida["hora_salida"]) == (
        "2026-10-09",
        "salida_anticipada",
        "19:00:00",
    )
    assert falta["docente"]["id"] == repetida["docente"]["id"] == escuela["docentes"][ALFA]
    assert falta["tipo"] == "falta" and falta["hora_salida"] is None
    # Sin horas elegidas nada está listo: una falta no se extiende sola a toda la jornada.
    assert all("Elige las horas que no se cumplieron" in f["problemas"] for f in (salida, falta))
    assert mala["fecha"] is None
    assert any("Fecha incorrecta" in p and "35/10/2026" in p for p in mala["problemas"])
    assert nadie["docente"] is None
    assert any("Docente no encontrado" in p for p in nadie["problemas"])
    assert any("Posible duplicado" in p for p in falta["problemas"])
    # La evidencia original se conserva tal cual.
    assert salida["detalle_texto"] == "Salió a las 7:00 p. m., una hora antes"
    assert salida["fila"] == 3  # título + encabezado


def test_el_mismo_archivo_no_se_registra_dos_veces(cliente, como_admin, escuela, sesion):
    primera = cargar(cliente, como_admin)
    r = subir(cliente, como_admin, nombre="otro-nombre.xlsx")
    assert r.status_code == 200 and r.json()["ya_existia"] is True
    assert r.json()["id"] == primera["id"]
    assert sesion.scalar(select(func.count()).select_from(ImportacionIncidencias)) == 1
    assert sesion.scalar(select(func.count()).select_from(IncidenciaImportada)) == 5


@pytest.mark.parametrize(
    "contenido,mensaje",
    [
        (b"esto no es un excel", "no es un Excel"),
        (excel(encabezado=("DIA DE LA SEMANA", "MATERIA", "GRUPO", "AULA")), "No se encontraron"),
        (excel(filas=[]), "no tiene incidencias"),
    ],
)
def test_archivo_invalido_no_guarda_nada(cliente, como_admin, escuela, sesion, contenido, mensaje):
    r = subir(cliente, como_admin, contenido)
    assert r.status_code == 422 and mensaje in r.json()["detail"]
    assert sesion.scalar(select(func.count()).select_from(ImportacionIncidencias)) == 0


def test_consulta_no_puede_importar_incidencias(cliente, como_consulta, escuela):
    assert subir(cliente, como_consulta).status_code == 403


# --- caso especial: salida anticipada ---------------------------------------------------


def test_salida_anticipada_solo_registra_las_horas_elegidas(cliente, como_admin, escuela, sesion):
    d = cargar(cliente, como_admin)
    salida = fila(d, 0)
    disponibles = horas(cliente, como_admin, salida["id"])
    assert [
        (h["programado_inicio"][:5], h["sugerida"], h["seleccionada"]) for h in disponibles
    ] == [
        ("17:00", False, False),
        ("18:00", False, False),
        ("19:00", True, False),  # solo se sugiere; nada se marca sin elegirlo
    ]
    assert disponibles[0]["se_registrara"]["error"].startswith("La hora 17:00–18:00 termina")
    salida = elegir(cliente, como_admin, salida["id"], "19:00")
    assert salida["lista"] is True, salida["problemas"]
    r = importar(cliente, como_admin, d["id"], salida["id"])
    assert r.status_code == 200, r.text
    assert r.json()["horas"] == 1
    [registro] = registros(sesion)
    assert (registro.programado_inicio, registro.estado) == (time(19), "falto")
    assert "Salida anticipada a las 19:00" in registro.observaciones
    # Las horas anteriores siguen pendientes: no se marcó toda la jornada.
    dia = cliente.get(
        "/bitacora/horas",
        params={"fecha": "2026-10-09", "docente_id": escuela["docentes"][OMEGA]},
        headers=como_admin,
    ).json()
    assert [f["estado"] for f in dia["filas"]] == ["pendiente", "pendiente", "falto"]
    # Aparece en el reporte de asistencia por hora.
    reporte = cliente.get(
        "/bitacora/horas/reporte",
        params={"desde": "2026-10-09", "hasta": "2026-10-09", "formato": "xlsx"},
        headers=como_admin,
    )
    assert reporte.status_code == 200
    textos = [
        str(c)
        for hoja in load_workbook(io.BytesIO(reporte.content)).worksheets
        for f in hoja.iter_rows(values_only=True)
        for c in f
        if c
    ]
    assert any("Salida anticipada a las 19:00" in t for t in textos)


def test_salida_a_mitad_de_hora_registra_presencia_parcial(cliente, como_admin, escuela, sesion):
    d = cargar(cliente, como_admin)
    salida = editar(cliente, como_admin, fila(d, 0)["id"], hora_salida="18:30")
    salida = elegir(cliente, como_admin, salida["id"], "18:00", "19:00")
    assert importar(cliente, como_admin, d["id"], salida["id"]).status_code == 200
    parcial, completa = registros(sesion)
    assert (parcial.estado, parcial.hora_entrada, parcial.hora_salida) == (
        "parcial",
        time(18),
        time(18, 30),
    )
    assert parcial.minutos_cumplidos == 30
    assert (completa.estado, completa.minutos_cumplidos) == ("falto", 0)


# --- confirmación, pendientes y atomicidad ----------------------------------------------


def test_solo_se_importan_las_filas_confirmadas_y_completas(cliente, como_admin, escuela, sesion):
    d = cargar(cliente, como_admin)
    falta = fila(d, 1)
    r = importar(cliente, como_admin, d["id"], falta["id"])  # sin horas: no se inventan
    assert r.status_code == 422
    assert any("Elige las horas" in p for p in r.json()["problemas"])
    assert registros(sesion) == []
    salida = elegir(cliente, como_admin, fila(d, 0)["id"], "19:00")
    assert importar(cliente, como_admin, d["id"], salida["id"]).status_code == 200
    d = cliente.get(f"/incidencias-excel/{d['id']}", headers=como_admin).json()
    assert (d["importadas"], d["pendientes"]) == (1, 4)
    assert [f["estado"] for f in d["filas"]] == ["importada"] + ["pendiente"] * 4
    # Una fila importada no se vuelve a importar ni se corrige aquí.
    assert importar(cliente, como_admin, d["id"], salida["id"]).status_code == 409
    r = cliente.patch(
        f"/incidencias-excel/filas/{salida['id']}", json={"motivo": "otro"}, headers=como_admin
    )
    assert r.status_code == 409
    assert len(registros(sesion)) == 1


def test_si_una_hora_falla_no_se_guarda_ninguna(cliente, como_admin, escuela, sesion, monkeypatch):
    d = cargar(cliente, como_admin)
    salida = elegir(cliente, como_admin, fila(d, 0)["id"], "19:00")
    falta = elegir(cliente, como_admin, fila(d, 1)["id"], "07:00", "08:00")
    descartar = cliente.post(
        f"/incidencias-excel/filas/{fila(d, 2)['id']}/descartar",
        json={"motivo": "Repetida en el archivo ficticio"},
        headers=como_admin,
    )
    assert descartar.status_code == 200
    original = servicio_horas.registrar
    llamadas = []

    def falla_en_la_tercera(*args, **kwargs):
        llamadas.append(1)
        if len(llamadas) == 3:
            raise ErrorNegocio("Falla simulada al guardar", 409)
        return original(*args, **kwargs)

    monkeypatch.setattr(servicio_horas, "registrar", falla_en_la_tercera)
    r = importar(cliente, como_admin, d["id"], salida["id"], falta["id"])
    assert r.status_code == 409 and r.json()["detail"].startswith("No se importó nada")
    assert registros(sesion) == []
    d = cliente.get(f"/incidencias-excel/{d['id']}", headers=como_admin).json()
    assert d["importadas"] == 0
    monkeypatch.setattr(servicio_horas, "registrar", original)
    r = importar(cliente, como_admin, d["id"], salida["id"], falta["id"])
    assert r.status_code == 200, r.text
    assert len(registros(sesion)) == 3


def test_no_sobrescribe_una_asistencia_ya_registrada(cliente, como_admin, escuela, sesion):
    dia = cliente.get(
        "/bitacora/horas",
        params={"fecha": "2026-10-08", "docente_id": escuela["docentes"][ALFA]},
        headers=como_admin,
    ).json()["filas"]
    previo = {k: dia[0][k] for k in ("docente_id", "fecha", "bloque_id", "programado_inicio")}
    assert cliente.post(
        "/asistencias/horas", json={**previo, "estado": "asistio"}, headers=como_admin
    ).is_success
    d = cargar(cliente, como_admin)
    falta = elegir(cliente, como_admin, fila(d, 1)["id"], "07:00")
    assert any("ya tiene registro (asistio)" in p for p in falta["problemas"])
    assert importar(cliente, como_admin, d["id"], falta["id"]).status_code == 422
    [registro] = registros(sesion)
    assert registro.estado == "asistio" and registro.correcciones == 0


def test_incidencia_repetida_se_detecta_y_se_resuelve_descartando(
    cliente, como_admin, escuela, sesion
):
    d = cargar(cliente, como_admin)
    a = elegir(cliente, como_admin, fila(d, 1)["id"], "07:00")
    b = elegir(cliente, como_admin, fila(d, 2)["id"], "07:00")
    assert any("Posible duplicado: la fila 5" in p for p in a["problemas"])
    assert any("Posible duplicado: la fila 4" in p for p in b["problemas"])
    corta = cliente.post(
        f"/incidencias-excel/filas/{b['id']}/descartar", json={"motivo": "no"}, headers=como_admin
    )
    assert corta.status_code == 422
    r = cliente.post(
        f"/incidencias-excel/filas/{b['id']}/descartar",
        json={"motivo": "Repetida en el archivo ficticio"},
        headers=como_admin,
    )
    assert r.json()["estado"] == "descartada"
    a = cliente.get(f"/incidencias-excel/{d['id']}", headers=como_admin).json()["filas"][1]
    assert a["lista"] is True, a["problemas"]
    assert importar(cliente, como_admin, d["id"], a["id"]).status_code == 200
    # Se puede recuperar la descartada, pero ahora choca con la ya importada.
    r = cliente.post(f"/incidencias-excel/filas/{b['id']}/recuperar", headers=como_admin)
    assert r.json()["estado"] == "pendiente"
    assert any("Posible duplicado" in p for p in r.json()["problemas"])
    assert any("ya tiene registro (falto)" in p for p in r.json()["problemas"])


def test_falta_justificada_pide_motivo_y_se_registra_justificada(
    cliente, como_admin, escuela, sesion
):
    d = cargar(cliente, como_admin)
    falta = elegir(cliente, como_admin, fila(d, 1)["id"], "07:00", "08:00")
    falta = editar(cliente, como_admin, falta["id"], justificada=True)
    assert "Escribe el motivo de la justificación" in falta["problemas"]
    falta = editar(
        cliente,
        como_admin,
        falta["id"],
        motivo="Comisión ficticia",
        observaciones="Oficio ficticio 123",
    )
    cliente.post(
        f"/incidencias-excel/filas/{fila(d, 2)['id']}/descartar",
        json={"motivo": "Repetida en el archivo ficticio"},
        headers=como_admin,
    )
    assert importar(cliente, como_admin, d["id"], falta["id"]).status_code == 200
    assert [(r.estado, r.justificacion) for r in registros(sesion)] == [
        ("justificado", "Comisión ficticia")
    ] * 2
    assert all("Oficio ficticio 123" in r.observaciones for r in registros(sesion))


def test_correcciones_de_la_vista_previa_se_guardan_y_se_auditan(
    cliente, como_admin, escuela, sesion
):
    d = cargar(cliente, como_admin)
    nadie, mala = fila(d, 4), fila(d, 3)
    beta = escuela["docentes"][BETA]
    nadie = editar(cliente, como_admin, nadie["id"], docente_id=beta, fecha="2026-10-07")
    assert nadie["docente_estado"] == "confirmado"
    assert not any("Docente no encontrado" in p for p in nadie["problemas"])
    mala = editar(cliente, como_admin, mala["id"], fecha="2026-10-14")
    assert not any("Fecha incorrecta" in p for p in mala["problemas"])
    futura = editar(cliente, como_admin, mala["id"], fecha="2026-11-18")
    assert "La fecha es futura" in futura["problemas"]
    r = cliente.patch(
        f"/incidencias-excel/filas/{nadie['id']}", json={"docente_id": beta}, headers=como_admin
    )
    assert r.status_code == 422  # sin cambios
    # Persisten al volver a consultar (otra petición, otra sesión).
    d = cliente.get(f"/incidencias-excel/{d['id']}", headers=como_admin).json()
    assert d["filas"][4]["docente"]["id"] == beta and d["filas"][3]["fecha"] == "2026-11-18"
    acciones = sesion.scalars(
        select(Auditoria.accion).where(Auditoria.entidad == "incidencia_importada")
    ).all()
    assert acciones.count("editar") == 3
    assert (
        sesion.scalar(
            select(func.count())
            .select_from(Auditoria)
            .where(Auditoria.entidad == "importacion_incidencias", Auditoria.accion == "importar")
        )
        == 1
    )


def test_dia_inhabil_no_se_importa_sin_excepcion(cliente, como_admin, escuela, sesion):
    r = cliente.post(
        "/calendario",
        json={
            "tipo": "inhabil",
            "fecha_inicio": "2026-10-08",
            "fecha_fin": "2026-10-08",
            "descripcion": "Suspensión ficticia",
        },
        headers=como_admin,
    )
    assert r.status_code == 201, r.text
    d = cargar(cliente, como_admin)
    falta = elegir(cliente, como_admin, fila(d, 1)["id"], "07:00")
    assert any("Día inhábil" in p for p in falta["problemas"])
    assert importar(cliente, como_admin, d["id"], falta["id"]).status_code == 422
    assert registros(sesion) == []


# --- lectura del archivo (sin base de datos) ------------------------------------------------


@pytest.mark.parametrize(
    "valor,esperado",
    [
        ("7:00 p. m.", time(19)),
        ("Salió a las 7:00 p.m., una hora antes", time(19)),
        ("19:00", time(19)),
        ("7 pm", time(19)),
        ("18 hrs", time(18)),
        ("12:30 a. m.", time(0, 30)),
        ("09.10.2026", None),  # una fecha no es una hora
        ("salió 1 hora antes", None),  # sin hora concreta no se inventa
        ("", None),
    ],
)
def test_leer_hora(valor, esperado):
    assert lector.leer_hora(valor) == esperado


@pytest.mark.parametrize(
    "valor,esperado",
    [
        (datetime(2026, 10, 9), date(2026, 10, 9)),
        ("09/10/2026", date(2026, 10, 9)),  # día/mes/año
        ("2026-10-09", date(2026, 10, 9)),
        ("9 de octubre de 2026", date(2026, 10, 9)),
        ("9/10/26", date(2026, 10, 9)),
        ("31/02/2026", None),
        ("viernes", None),
        (None, None),
    ],
)
def test_leer_fecha(valor, esperado):
    assert lector.leer_fecha(valor) == esperado


@pytest.mark.parametrize(
    "valor,esperado",
    [
        ("FALTA", "falta"),
        ("Inasistencia", "falta"),
        ("Salida anticipada", "salida_anticipada"),
        ("Se retira antes", "salida_anticipada"),
        ("Falta y salida", None),  # ambigua: la elige el usuario
        ("Permiso", None),
    ],
)
def test_leer_tipo(valor, esperado):
    assert lector.leer_tipo(valor) == esperado


def test_buscar_docente_sin_asignar_dudosos():
    catalogo = [
        (1, "PRUEBA LARA OMEGA ERNESTO"),
        (2, "DOCENTE FICTICIO ALFA"),
        (3, "MARIA DE LA LUZ FICTICIA"),
        (4, "MARIA FICTICIA GOMEZ"),
    ]
    assert lector.buscar_docente("Lara Omega Ernesto Prueba", catalogo) == (1, "coincide")
    assert lector.buscar_docente("Lara Omega Ernesto", catalogo) == (1, "sugerido")
    assert lector.buscar_docente("Ficticia Maria", catalogo) == (None, "sin_coincidencia")
    assert lector.buscar_docente("Docente Inexistente", catalogo) == (None, "sin_coincidencia")
    assert lector.buscar_docente("", catalogo) == (None, "sin_coincidencia")
