"""Conversión entre bloques de la API y la cuadrícula semanal."""

import pytest

from asi_cliente.cuadricula import Celda, CuadriculaNoCompatible, bloques_a_celdas, celdas_a_bloques


def bloque_api(dia, inicio, fin, asignatura, grupo=None, aula=None):
    return {
        "dia": dia,
        "hora_inicio": inicio,
        "hora_fin": fin,
        "asignatura": {"id": asignatura, "nombre": "X", "tipo": "materia"},
        "grupo": {"id": grupo, "clave": "A"} if grupo else None,
        "aula": {"id": aula, "clave": "M01"} if aula else None,
    }


def test_bloque_de_dos_horas_ocupa_dos_celdas():
    celdas = bloques_a_celdas([bloque_api("lunes", "07:00:00", "09:00:00", 1, 2, 3)])
    assert celdas == {("lunes", 7): Celda(1, 2, 3), ("lunes", 8): Celda(1, 2, 3)}


def test_celdas_consecutivas_iguales_forman_un_bloque():
    celdas = {
        ("lunes", 7): Celda(1, 2, 3),
        ("lunes", 8): Celda(1, 2, 3),
        ("lunes", 9): Celda(1, 2, 4),  # otra aula: bloque distinto
        ("lunes", 11): Celda(1, 2, 4),  # hueco a las 10: bloque distinto
        ("sabado", 22): Celda(5),
    }
    bloques = [
        (b["dia"], b["hora_inicio"], b["hora_fin"], b["aula_id"]) for b in celdas_a_bloques(celdas)
    ]
    assert bloques == [
        ("lunes", "07:00", "09:00", 3),
        ("lunes", "09:00", "10:00", 4),
        ("lunes", "11:00", "12:00", 4),
        ("sabado", "22:00", "23:00", None),
    ]


def test_ida_y_vuelta_conserva_el_horario():
    api = [
        bloque_api("martes", "15:00", "18:00", 7, 1, 2),
        bloque_api("viernes", "07:00", "08:00", 8, None, 9),
    ]
    regreso = celdas_a_bloques(bloques_a_celdas(api))
    assert [(b["dia"], b["hora_inicio"], b["hora_fin"]) for b in regreso] == [
        ("martes", "15:00", "18:00"),
        ("viernes", "07:00", "08:00"),
    ]


def test_bloque_con_media_hora_no_cabe_en_la_cuadricula():
    with pytest.raises(CuadriculaNoCompatible):
        bloques_a_celdas([bloque_api("lunes", "07:30", "09:00", 1)])
