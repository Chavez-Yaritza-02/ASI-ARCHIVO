"""Conversión entre bloques de horario (API) y la cuadrícula semanal de la interfaz.

La cuadrícula usa celdas de una hora, igual que los horarios institucionales
(07:00 a 23:00, lunes a sábado). La API guarda bloques continuos:
    lunes 07:00–09:00 CÁLC. DIF.  ->  celdas (lunes, 7) y (lunes, 8)
"""

from dataclasses import dataclass

from PySide6.QtCore import QEvent, QObject, QTimer

DIAS = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado"]
TITULOS_DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"]
HORAS = list(range(7, 23))  # filas: 07:00 … 22:00 (la última termina a las 23:00)


@dataclass(frozen=True)
class Celda:
    asignatura_id: int
    grupo_id: int | None = None
    aula_id: int | None = None
    grupo_letra: str | None = None  # letra pendiente de validación (sin grupo completo)


ALTO_FILA = 40  # alto mínimo de una hora con clase o vacía dentro del horario
ALTO_COMPACTO = 24  # horas vacías fuera del horario, solo si así cabe todo sin desplazarse


class _AjusteInicial(QObject):
    """Ajusta las filas al espacio disponible y mantiene visible la primera clase.

    - Con `ajustar`, las filas crecen para llenar el alto disponible; si el horario no cabe,
      se compactan las horas vacías fuera de él. Se recalcula al cambiar el tamaño.
    - El desplazamiento a la primera clase se repite al mostrarse o redimensionar, hasta
      que el usuario desplace la tabla a mano.
    """

    def __init__(self, tabla):
        super().__init__(tabla)
        self.tabla, self.fila, self.activo, self._moviendo = tabla, None, False, False
        self.ajustar, self.horas = False, []
        self._pendiente = False
        tabla.viewport().installEventFilter(self)
        # Solo cuenta lo que hace el usuario (rueda, arrastre, flechas), no los cambios de
        # rango que provoca redimensionar la ventana.
        tabla.verticalScrollBar().actionTriggered.connect(self._movido)

    def _movido(self, *_):
        if not self._moviendo:
            self.activo = False  # lo desplazó el usuario: no volver a moverlo

    def eventFilter(self, _objeto, evento):
        if self._moviendo or evento.type() not in (QEvent.Show, QEvent.Resize):
            return False
        # Después de que Qt termine de acomodar la tabla (barras y encabezados): si se
        # aplica dentro del propio evento, el desplazamiento queda a medias.
        if not self._pendiente:
            self._pendiente = True
            QTimer.singleShot(0, self._reajustar)
        return False

    def _reajustar(self):
        self._pendiente = False
        if self.ajustar:
            self.ajustar_filas()
        if self.activo:
            self.aplicar()

    def ajustar_filas(self):
        tabla = self.tabla
        disponible = tabla.viewport().height()
        if disponible <= 0:
            return
        self._moviendo = True
        try:
            tabla.resizeRowsToContents()
            alturas = [max(tabla.rowHeight(i), ALTO_FILA) for i in range(tabla.rowCount())]
            if sum(alturas) > disponible and self.horas:
                inicio, fin = HORAS.index(min(self.horas)), HORAS.index(max(self.horas))
                # Lo justo para que la hora se lea completa en el encabezado de la fila.
                compacta = max(
                    ALTO_COMPACTO,
                    max(
                        tabla.verticalHeader().sectionSizeFromContents(i).height()
                        for i in range(tabla.rowCount())
                    ),
                )
                for i in range(len(alturas)):
                    vacia = not any(tabla.item(i, c) for c in range(tabla.columnCount()))
                    if vacia and not inicio <= i <= fin:
                        alturas[i] = compacta
            sobra = disponible - sum(alturas)
            if sobra > 0:  # cabe: se reparte el espacio y no hay que desplazarse
                for i in range(len(alturas)):
                    alturas[i] += sobra // len(alturas) + (1 if i < sobra % len(alturas) else 0)
            for i, alto in enumerate(alturas):
                tabla.setRowHeight(i, alto)
        finally:
            self._moviendo = False

    def aplicar(self):
        tabla, fila = self.tabla, self.fila
        if fila is None:
            return
        self._moviendo = True
        try:
            if fila == 0:
                tabla.verticalScrollBar().setValue(0)
            else:
                alto = tabla.viewport().height()
                # Todo el horario (de la primera a la última clase) a la vista si cabe; una
                # hora antes como referencia solo si también cabe.
                ultima = HORAS.index(max(self.horas)) if self.horas else fila
                horario = sum(tabla.rowHeight(i) for i in range(fila, ultima + 1))
                if horario > alto:
                    horario = tabla.rowHeight(fila)
                previa = fila - 1
                cabe = tabla.rowHeight(previa) + horario <= alto
                tabla.scrollTo(
                    tabla.model().index(previa if cabe else fila, 0),
                    tabla.ScrollHint.PositionAtTop,
                )
        finally:
            self._moviendo = False


def fila_visible_completa(tabla, fila: int) -> bool:
    """True si la fila se ve entera (ni la hora ni el contenido quedan cortados)."""
    y = tabla.rowViewportPosition(fila)
    return y >= 0 and y + tabla.rowHeight(fila) <= tabla.viewport().height()


def mostrar_primera_clase(tabla, horas_ocupadas, ajustar: bool = False) -> None:
    """Desplaza la cuadrícula hasta la primera hora con clase (p. ej. turno vespertino).

    Sin esto, un horario que empieza a las 17:00 parece vacío porque se ve desde las 07:00.
    Con `ajustar=True` además las filas llenan el alto disponible (sin desplazarse si cabe).
    """
    horas = sorted(h for h in horas_ocupadas if h in HORAS)
    ajuste = tabla.findChild(_AjusteInicial) or _AjusteInicial(tabla)
    ajuste.fila = HORAS.index(horas[0]) if horas else 0
    ajuste.horas, ajuste.ajustar = horas, ajustar
    ajuste.activo = True
    if ajustar:
        tabla.verticalHeader().setMinimumSectionSize(ALTO_COMPACTO)
        ajuste.ajustar_filas()
    ajuste.aplicar()


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
            None if b.get("grupo") else b.get("grupo_letra"),
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
            "grupo_letra": b["_celda"].grupo_letra,
        }
        for b in bloques
    ]
