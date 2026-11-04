"""Docentes, asignaturas, grupos y aulas (datos ficticios)."""

from sqlalchemy import select

from app.models import Auditoria


def test_crear_y_consultar_docente(cliente, como_admin):
    r = cliente.post(
        "/docentes",
        json={"nombre": "  Gámma  Prueba   María ", "nomina": "ZZZ0001", "correo": "MG@Prueba.mx"},
        headers=como_admin,
    )
    assert r.status_code == 201, r.text
    docente = r.json()
    assert docente["nombre"] == "GÁMMA PRUEBA MARÍA"  # espacios limpios, acentos conservados
    assert docente["correo"] == "mg@prueba.mx"
    assert docente["activo"] is True
    assert cliente.get(f"/docentes/{docente['id']}", headers=como_admin).json() == docente


def test_docente_duplicado_aunque_cambien_acentos(cliente, como_admin):
    cliente.post("/docentes", json={"nombre": "ÍÑIGO PRUEBA ÁNGEL"}, headers=como_admin)
    r = cliente.post("/docentes", json={"nombre": "inigo prueba angel"}, headers=como_admin)
    assert r.status_code == 409
    assert "ya existe" in r.json()["detail"]


def test_nomina_no_se_repite(cliente, como_admin):
    cliente.post("/docentes", json={"nombre": "UNO PRUEBA", "nomina": "N1"}, headers=como_admin)
    r = cliente.post("/docentes", json={"nombre": "DOS PRUEBA", "nomina": "N1"}, headers=como_admin)
    assert r.status_code == 409 and "nómina" in r.json()["detail"]


def test_buscar_sin_acentos_y_filtrar_activos(cliente, como_admin):
    for nombre in ("ÁLFA PRUEBA ANA", "BETA DÍAZPRUEBA LUIS", "CETA PRUEBA EVA"):
        cliente.post("/docentes", json={"nombre": nombre}, headers=como_admin)
    encontrados = cliente.get("/docentes?buscar=diazprueba", headers=como_admin).json()
    assert [d["nombre"] for d in encontrados] == ["BETA DÍAZPRUEBA LUIS"]

    cliente.post("/docentes/1/desactivar", headers=como_admin)
    activos = cliente.get("/docentes?activo=true", headers=como_admin).json()
    assert [d["id"] for d in activos] == [2, 3]
    todos = cliente.get("/docentes", headers=como_admin).json()
    assert [d["nombre"] for d in todos][0] == "ÁLFA PRUEBA ANA"  # orden alfabético


def test_editar_activar_y_auditar_docente(cliente, como_admin, sesion):
    cliente.post("/docentes", json={"nombre": "SIGMA PRUEBA RAÚL"}, headers=como_admin)
    r = cliente.patch("/docentes/1", json={"correo": "rt@prueba.mx"}, headers=como_admin)
    assert r.json()["correo"] == "rt@prueba.mx"
    assert cliente.post("/docentes/1/desactivar", headers=como_admin).json()["activo"] is False
    assert cliente.post("/docentes/1/activar", headers=como_admin).json()["activo"] is True

    registros = sesion.scalars(
        select(Auditoria).where(Auditoria.entidad == "docente").order_by(Auditoria.id)
    ).all()
    assert [a.accion for a in registros] == ["crear", "editar", "desactivar", "activar"]
    assert registros[1].antes["correo"] is None
    assert registros[1].despues["correo"] == "rt@prueba.mx"


def test_editar_sin_cambios_no_genera_auditoria(cliente, como_admin, sesion):
    cliente.post("/docentes", json={"nombre": "SIN CAMBIOS PRUEBA"}, headers=como_admin)
    cliente.patch("/docentes/1", json={"nombre": "sin cambios prueba"}, headers=como_admin)
    acciones = sesion.scalars(select(Auditoria.accion).where(Auditoria.entidad == "docente"))
    assert list(acciones) == ["crear"]


def test_consulta_puede_ver_pero_no_modificar(cliente, como_admin, como_consulta):
    cliente.post("/docentes", json={"nombre": "SOLO LECTURA PRUEBA"}, headers=como_admin)
    assert cliente.get("/docentes", headers=como_consulta).status_code == 200
    assert (
        cliente.post("/docentes", json={"nombre": "X Y Z"}, headers=como_consulta).status_code
        == 403
    )
    assert cliente.post("/docentes/1/desactivar", headers=como_consulta).status_code == 403
    assert cliente.post("/aulas", json={"clave": "M01"}, headers=como_consulta).status_code == 403


def test_docente_inexistente_y_datos_invalidos(cliente, como_admin):
    assert cliente.get("/docentes/999", headers=como_admin).status_code == 404
    assert cliente.post("/docentes", json={"nombre": "AB"}, headers=como_admin).status_code == 422
    r = cliente.post(
        "/docentes", json={"nombre": "ABC DEF", "correo": "no-es-correo"}, headers=como_admin
    )
    assert r.status_code == 422


def test_asignaturas_grupos_y_aulas(cliente, como_admin):
    r = cliente.post("/asignaturas", json={"nombre": "CÁLC. DIF."}, headers=como_admin)
    assert r.status_code == 201 and r.json()["tipo"] == "materia"
    # Misma asignatura escrita sin acentos ni puntos: duplicada.
    r = cliente.post("/asignaturas", json={"nombre": "calc dif"}, headers=como_admin)
    assert r.status_code == 409
    r = cliente.post(
        "/asignaturas", json={"nombre": "TUTORÍA", "tipo": "actividad"}, headers=como_admin
    )
    assert r.json()["tipo"] == "actividad"
    r = cliente.post(
        "/asignaturas", json={"nombre": "OTRA", "tipo": "inventado"}, headers=como_admin
    )
    assert r.status_code == 422

    assert cliente.post("/grupos", json={"clave": "a"}, headers=como_admin).json()["clave"] == "A"
    assert cliente.post("/grupos", json={"clave": "A"}, headers=como_admin).status_code == 409
    aula = cliente.post(
        "/aulas", json={"clave": "sala em", "descripcion": "Sala de maestros"}, headers=como_admin
    ).json()
    assert aula["clave"] == "SALA EM"
    assert cliente.get("/aulas?buscar=sala", headers=como_admin).json()[0]["id"] == aula["id"]
