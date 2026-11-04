"""Conversión entre bloques de horario (API) y la cuadrícula semanal de la interfaz.

La cuadrícula usa celdas de una hora, igual que los horarios institucionales
(07:00 a 23:00, lunes a sábado). La API guarda bloques continuos:
    lunes 07:00–09:00 CÁLC. DIF.  ->  celdas (lunes, 7) y (lunes, 8)
"""

from dataclasses import dataclass

DIAS = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado"]
TITULOS_DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"]
HORAS = list(range(7, 23))  # filas: 07:00 … 22:00 (la última termina a las 23:00)


@dataclass(frozen=True)
class Celda:
    asignatura_id: int
    grupo_id: int | None = None
    aula_id: int | None = None


class CuadriculaNoCompatible(ValueError):
    """El horario tiene bloques que no empiezan o terminan en hora exacta."""


def _hora(texto: str) -> tuple[int, int]:
    h, m = texto.split(":")[:2]
    return int(h), int(m)


def bloques_a_celdas(bloques: list[dict]) -> dict[tuple[str, int], Celda]:
    celdas: dict[tuple[str, int], Celda] = {}
    for b in bloques:
        (h_ini, m_ini), (h_fin, m_fin) = _hora(b["hora_inicio"]), _hora(b["hora_fin"])
        if m_ini or m_fin or h_ini < HORAS[0] or h_fin > HORAS[-1] + 1:
            raise CuadriculaNoCompatible(
                f"{b['dia']} {b['hora_inicio'][:5]}–{b['hora_fin'][:5]} no cabe en la cuadrícula"
            )
        celda = Celda(
            b["asignatura"]["id"],
            b["grupo"]["id"] if b.get("grupo") else None,
            b["aula"]["id"] if b.get("aula") else None,
        )
        for h in range(h_ini, h_fin):
            celdas[(b["dia"], h)] = celda
    return celdas


def celdas_a_bloques(celdas: dict[tuple[str, int], Celda]) -> list[dict]:
    """Une horas consecutivas idénticas del mismo día en un solo bloque."""
    bloques: list[dict] = []
    for dia in DIAS:
        actual: dict | None = None
        for h in HORAS:
            celda = celdas.get((dia, h))
            if actual and celda == actual["_celda"] and actual["_fin"] == h:
                actual["_fin"] = h + 1
                continue
            if actual:
                bloques.append(actual)
            actual = {"_dia": dia, "_celda": celda, "_inicio": h, "_fin": h + 1} if celda else None
        if actual:
            bloques.append(actual)
    return [
        {
            "dia": b["_dia"],
            "hora_inicio": f"{b['_inicio']:02d}:00",
            "hora_fin": f"{b['_fin']:02d}:00",
            "asignatura_id": b["_celda"].asignatura_id,
            "grupo_id": b["_celda"].grupo_id,
            "aula_id": b["_celda"].aula_id,
        }
        for b in bloques
    ]
