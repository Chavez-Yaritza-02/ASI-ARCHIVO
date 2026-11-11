"""Captura de varias horas en una sola transacción, con estado por fila."""

from PySide6.QtCore import QTime
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QLineEdit,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTimeEdit,
    QVBoxLayout,
)


class DialogoCapturaLote(QDialog):
    def __init__(self, filas, padre=None):
        super().__init__(padre)
        self.setWindowTitle("Registrar horas seleccionadas")
        self.resize(1100, 520)
        self.filas, self.controles = filas, []
        tabla = QTableWidget(len(filas), 7)
        tabla.setHorizontalHeaderLabels(
            [
                "Docente / hora",
                "Estado",
                "Entrada",
                "Salida",
                "Justificados min",
                "Justificación",
                "Excepción inhábil",
            ]
        )
        tabla.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        for i, f in enumerate(filas):
            tabla.setItem(
                i,
                0,
                QTableWidgetItem(
                    f"{f['docente_nombre']}\n{f['programado_inicio'][:5]}–{f['programado_fin'][:5]}"
                ),
            )
            estado = QComboBox()
            for texto, clave in [
                ("Asistió", "asistio"),
                ("Falta", "falto"),
                ("Retardo", "retardo"),
                ("Justificado", "justificado"),
                ("Parcial", "parcial"),
            ]:
                estado.addItem(texto, clave)
            entrada, salida = QTimeEdit(), QTimeEdit()
            for control, valor in (
                (entrada, f["programado_inicio"]),
                (salida, f["programado_fin"]),
            ):
                control.setDisplayFormat("HH:mm")
                control.setTime(QTime.fromString(valor[:5], "HH:mm"))
            minutos = QSpinBox()
            minutos.setRange(0, f["minutos"]["programadas"])
            motivo = QLineEdit()
            excepcion = QCheckBox("Autorizar")
            excepcion.setEnabled(not f["dia_habil"])
            controles = (estado, entrada, salida, minutos, motivo, excepcion)
            self.controles.append(controles)
            for j, control in enumerate(controles, 1):
                tabla.setCellWidget(i, j, control)

            def actualizar(_=None, controles=controles):
                e, inicio, fin, m, texto, _ex = controles
                parcial = e.currentData() == "parcial"
                inicio.setEnabled(parcial or e.currentData() == "retardo")
                fin.setEnabled(parcial or e.currentData() == "retardo")
                m.setEnabled(parcial)
                texto.setEnabled(parcial or e.currentData() == "justificado")

            estado.currentIndexChanged.connect(actualizar)
            actualizar()
        tabla.resizeRowsToContents()
        botones = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        botones.button(QDialogButtonBox.Save).setText("Guardar")
        botones.button(QDialogButtonBox.Cancel).setText("Cancelar")
        botones.accepted.connect(self.accept)
        botones.rejected.connect(self.reject)
        capa = QVBoxLayout(self)
        capa.addWidget(
            QLabel(
                f"{len(filas)} horas: revisa cada estado antes de guardar. "
                "Si alguna fila falla, no se guardará ninguna.",
                wordWrap=True,
            )
        )
        capa.addWidget(tabla)
        capa.addWidget(botones)

    def datos(self):
        resultado = []
        for f, (estado, entrada, salida, minutos, motivo, excepcion) in zip(
            self.filas, self.controles, strict=True
        ):
            e = estado.currentData()
            resultado.append(
                {
                    "docente_id": f["docente_id"],
                    "fecha": f["fecha"],
                    "bloque_id": f["bloque_id"],
                    "programado_inicio": f["programado_inicio"],
                    "estado": e,
                    "hora_entrada": entrada.time().toString("HH:mm")
                    if e in ("parcial", "retardo")
                    else None,
                    "hora_salida": salida.time().toString("HH:mm")
                    if e in ("parcial", "retardo")
                    else None,
                    "minutos_justificados": minutos.value() if e == "parcial" else 0,
                    "justificacion": motivo.text().strip(),
                    "autorizar_dia_inhabil": excepcion.isChecked(),
                }
            )
        return {"registros": resultado}
