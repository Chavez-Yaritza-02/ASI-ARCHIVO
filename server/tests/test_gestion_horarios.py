"""Gestión de horarios por semestre: periodos independientes, choques, registro de
cambios y permisos. Solo datos ficticios en la base exclusiva de pruebas."""

import os

from horario_ficticio import UNO, pdf_escaneado
from test_horarios import base, bloque, bloques_validos, nuevo_borrador  # noqa: F401
from test_importacion import catalogo, importar, paginas  # noqa: F401

os.environ["ASI_OCR_PROCESOS"] = "1"


def confirmar(cliente, encabezados, horario_id, bloques, **extra):
    r = cliente.put(f"/horarios/{horario_id}/bloques", json=bloques, headers=encabezados)
    assert r.status_code == 200, r.text
    return cliente.post(f"/horarios/{horario_id}/confirmar", json=extra, headers=encabezados)


def test_grupo_ocupado_por_otro_docente_se_advierte(cliente, como_admin, base):  # noqa: F811
    otro = nuevo_borrador(cliente, como_admin, base, docente="docente2")
    r = confirmar(
        cliente,
        como_admin,
        otro["id"],
        [bloque("martes", "10:00", "12:00", base["fisica"], base["grupo_a"], base["m02"])],
    )
    assert r.json()["estado"] == "vigente"

    # Mismo grupo, otra aula, a la misma hora: el grupo no puede estar en dos clases.
    h = nuevo_borrador(cliente, como_admin, base)
    r = confirmar(
        cliente,
        como_admin,
        h["id"],
        [bloque("martes", "11:00", "12:00", base["calculo"], base["grupo_a"], base["m01"])],
    )
    assert r.status_code == 409
    problemas = r.json()["problemas"]
    assert any(p.startswith("Grupo ") and "DOCENTE PRUEBA DOS" in p for p in problemas)
    assert not any(p.startswith("Aula ") for p in problemas)  # aulas distintas


def test_importacion_avisa_choques_antes_de_aprobar(cliente, como_admin, catalogo):  # noqa: F811
    otro = cliente.post(
        "/docentes", json={"nombre": "DOCENTE PRUEBA DOS"}, headers=como_admin
    ).json()["id"]
    h = cliente.post(
        "/horarios",
        json={"docente_id": otro, "periodo_id": catalogo["periodo"]},
        headers=como_admin,
    ).json()
    r = confirmar(
        cliente,
        como_admin,
        h["id"],
        [bloque("lunes", "07:00", "08:00", catalogo["gestion"], None, catalogo["m01"])],
    )
    assert r.json()["estado"] == "vigente"

    detalle = importar(cliente, como_admin, catalogo["periodo"], "uno.pdf", pdf_escaneado(UNO))
    id_ = paginas(detalle)[0]["id"]
    pagina = cliente.get(f"/importaciones/paginas/{id_}", headers=como_admin).json()
    assert any("Aula M01 ocupada" in a and "DOCENTE PRUEBA DOS" in a for a in pagina["avisos"])


def test_periodos_independientes_conservan_el_historial(cliente, como_admin, base):  # noqa: F811
    v1 = nuevo_borrador(cliente, como_admin, base)
    lunes = [bloque("lunes", "07:00", "09:00", base["calculo"], base["grupo_a"], base["m01"])]
    assert confirmar(cliente, como_admin, v1["id"], lunes).json()["estado"] == "vigente"

    # Semestres siguientes: periodos nuevos, sin traslapar fechas.
    nuevos = {}
    for nombre, inicio, fin in (
        ("Enero - Junio 2027", "2027-01-15", "2027-06-30"),
        ("Agosto - Diciembre 2027", "2027-08-01", "2027-12-31"),
    ):
        r = cliente.post(
            "/periodos",
            json={"nombre": nombre, "fecha_inicio": inicio, "fecha_fin": fin},
            headers=como_admin,
        )
        assert r.status_code == 201, r.text
        nuevos[nombre] = r.json()["id"]
    assert cliente.post(f"/periodos/{base['periodo']}/cerrar", headers=como_admin).is_success
    enero = nuevos["Enero - Junio 2027"]
    assert cliente.post(f"/periodos/{enero}/activar", headers=como_admin).is_success
    activo = cliente.get("/periodos/activo", headers=como_admin).json()
    assert activo["nombre"] == "ENERO - JUNIO 2027"

    # El nuevo semestre recibe su propio horario; el anterior no se toca.
    r = cliente.post(
        "/horarios",
        json={"docente_id": base["docente"], "periodo_id": enero},
        headers=como_admin,
    )
    v_enero = r.json()
    viernes = [bloque("viernes", "10:00", "11:00", base["gestion"], None, base["m02"])]
    assert confirmar(cliente, como_admin, v_enero["id"], viernes).json()["estado"] == "vigente"

    antiguo = cliente.get(f"/horarios/{v1['id']}", headers=como_admin).json()
    assert antiguo["estado"] == "vigente" and antiguo["periodo"]["id"] == base["periodo"]
    assert [(b["dia"], b["hora_inicio"]) for b in antiguo["bloques"]] == [("lunes", "07:00:00")]
    por_periodo = {
        p: [
            h["id"]
            for h in cliente.get("/horarios", params={"periodo_id": p}, headers=como_admin).json()
        ]
        for p in (base["periodo"], enero)
    }
    assert por_periodo == {base["periodo"]: [v1["id"]], enero: [v_enero["id"]]}
    # El periodo cerrado queda de solo lectura.
    r = cliente.post(
        "/horarios",
        json={"docente_id": base["docente"], "periodo_id": base["periodo"]},
        headers=como_admin,
    )
    assert r.status_code == 409


def test_registro_de_cambios_y_permisos(
    cliente,
    como_admin,
    como_consulta,
    base,  # noqa: F811
    bloques_validos,  # noqa: F811
):
    v1 = nuevo_borrador(cliente, como_admin, base)
    confirmar(cliente, como_admin, v1["id"], bloques_validos)
    v2 = nuevo_borrador(cliente, como_admin, base, basado_en_id=v1["id"])
    confirmar(cliente, como_admin, v2["id"], bloques_validos[:1])

    r = cliente.get(
        "/horarios/cambios", params={"periodo_id": base["periodo"]}, headers=como_consulta
    )
    assert r.status_code == 200  # consulta puede ver el registro
    cambios = r.json()
    assert cambios[0]["accion"] == "Confirmó como vigente" and cambios[0]["version"] == 2
    assert any(c["detalle"] == "3 → 1 bloques" for c in cambios)
    assert any(c["accion"] == "Pasó al historial" and c["version"] == 1 for c in cambios)
    assert all(c["usuario"] and c["docente"] == "DOCENTE PRUEBA UNO" for c in cambios)
    otro = cliente.get(
        "/horarios/cambios", params={"docente_id": base["docente2"]}, headers=como_admin
    )
    assert otro.json() == []

    # Consulta solo visualiza: no importa, no edita, no confirma, no gestiona periodos.
    assert cliente.get("/horarios", headers=como_consulta).status_code == 200
    for metodo, ruta, datos in (
        ("post", "/horarios", {"docente_id": base["docente"], "periodo_id": base["periodo"]}),
        ("put", f"/horarios/{v2['id']}/bloques", []),
        ("post", f"/horarios/{v2['id']}/confirmar", {}),
        (
            "post",
            "/periodos",
            {"nombre": "X", "fecha_inicio": "2028-01-01", "fecha_fin": "2028-06-30"},
        ),
        ("post", f"/periodos/{base['periodo']}/cerrar", None),
    ):
        r = getattr(cliente, metodo)(ruta, json=datos, headers=como_consulta)
        assert r.status_code == 403, (ruta, r.status_code)
    r = cliente.post(
        "/importaciones",
        data={"periodo_id": str(base["periodo"])},
        files={"archivo": ("x.pdf", b"%PDF-1.4", "application/pdf")},
        headers=como_consulta,
    )
    assert r.status_code == 403
    assert cliente.get("/importaciones", headers=como_consulta).status_code == 403
