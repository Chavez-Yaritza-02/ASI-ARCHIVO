"""Registro rápido de asistencia por hora: una fila por hora con cuatro botones.

- Asistió y Falta se guardan con un clic.
- Retardo pide, en la misma fila, la hora real de llegada (ya escrita: la hora actual
  o el inicio más la tolerancia). Enter guarda.
- Justificado pide, en la misma fila, el motivo; después se puede adjuntar el
  justificante en el archivo digital.
- Cambiar un estado ya registrado es una corrección: pide el motivo (auditoría).
- Nada se marca solo: una hora sin registrar queda «Pendiente».

Sin ventanas emergentes: los avisos y errores se muestran dentro de cada fila.
"""

import unicodedata
from datetime import date, datetime, timedelta

from PySide6.QtCore import Qt, QTime
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from asi_cliente.api.cliente import ErrorApi

# Botones de captura: (estado, texto, icono). El color lo da la hoja de estilo.
BOTONES = (
    ("asistio", "Asistió", "●"),
    ("retardo", "Retardo", "●"),
    ("falto", "Falta", "●"),
    ("justificado", "Justificado", "●"),
)
ETIQUETAS = {
    "pendiente": "Pendiente",
    "inhabil": "Día inhábil",
    "asistio": "Asistió",
    "retardo": "Retardo",
    "falto": "Falta",
    "justificado": "Justificado",
    "parcial": "Parcial",
}
MOTIVO_OBSERVACION = "Se agregó o editó la observación del registro"


def normal(texto: str | None) -> str:
    plano = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()
    return " ".join(plano.upper().split())


def duracion(fila: dict) -> int:
    inicio = datetime.strptime(fila["programado_inicio"][:5], "%H:%M")
    fin = datetime.strptime(fila["programado_fin"][:5], "%H:%M")
    return int((fin - inicio).total_seconds() // 60)


def minutos_de(fila: dict, registro: dict | None) -> dict:
    """Mismos cálculos que el servidor, para actualizar la fila sin recargar todo el día."""
    total = duracion(fila)
    m = dict.fromkeys(
        (
            "programadas",
            "exigibles",
            "cumplidas",
            "faltantes",
            "justificadas",
            "pendientes",
            "suspendidas",
        ),
        0,
    )
    m["programadas"] = total
    if registro is None and not fila.get("dia_habil", True):
        m["suspendidas"] = total
        return m
    m["exigibles"] = total
    if registro is None:
        m["pendientes"] = total
    else:
        m["cumplidas"] = registro["minutos_cumplidos"]
        m["justificadas"] = registro["minutos_justificados"]
        m["faltantes"] = total - m["cumplidas"] - m["justificadas"]
    return m


def horas_texto(minutos: int) -> str:
    h, m = divmod(int(minutos), 60)
    if not m:
        return f"{h} h"
    return f"{h} h {m} min" if h else f"{m} min"


def llegada_sugerida(fila: dict, hoy: date, ahora: datetime) -> QTime:
    """Hora de llegada propuesta para un retardo (siempre dentro del tramo, después del inicio).

    Si la clase está en curso, la hora actual; si no, el inicio más la tolerancia.
    """
    inicio = datetime.strptime(fila["programado_inicio"][:5], "%H:%M")
    fin = datetime.strptime(fila["programado_fin"][:5], "%H:%M")
    ultimo = fin - timedelta(minutes=1)
    actual = datetime.strptime(ahora.strftime("%H:%M"), "%H:%M")
    if str(fila["fecha"]) == hoy.isoformat() and inicio < actual <= ultimo:
        propuesta = actual
    else:
        propuesta = inicio + timedelta(minutes=max(fila.get("tolerancia_minutos", 0) + 1, 1))
    propuesta = min(max(propuesta, inicio + timedelta(minutes=1)), ultimo)
    return QTime(propuesta.hour, propuesta.minute)


class Tarjeta(QFrame):
    """Indicador del resumen del día (mismo estilo que Inicio)."""

    def __init__(self, titulo: str, clave: str):
        super().__init__(objectName="indicador")
        self.clave = clave
        self.valor = QLabel("—", objectName="indicador_valor")
        self.titulo = QLabel(titulo, objectName="indicador_titulo", wordWrap=True)
        self.valor.setProperty("tono", clave)
        capa = QVBoxLayout(self)
        capa.setContentsMargins(16, 10, 16, 10)
        capa.setSpacing(0)
        capa.addWidget(self.valor)
        capa.addWidget(self.titulo)
        self.setAccessibleName(titulo)

    def poner(self, texto: str) -> None:
        self.valor.setText(texto)
        self.setAccessibleDescription(texto)


class FilaRapida(QFrame):
    """Una hora programada con sus cuatro botones, observación y avisos en la misma fila."""

    def __init__(self, fila: dict, vista):
        super().__init__(objectName="fila_asistencia")
        self.fila, self.vista = fila, vista
        self.estado_editor: str | None = None  # estado que espera datos en la fila
        self.ocupada = False
        self.puede = vista.usuario.puede("asistencia.registrar")

        hora = QLabel(
            f"{fila['programado_inicio'][:5]}\n{fila['programado_fin'][:5]}",
            objectName="fila_hora",
        )
        hora.setAlignment(Qt.AlignCenter)
        hora.setFixedWidth(64)
        self.docente = QLabel(fila["docente_nombre"], objectName="fila_docente")
        self.docente.setTextFormat(Qt.PlainText)
        self.docente.setWordWrap(True)
        detalle = [fila["asignatura"]]
        detalle += [f"Grupo {fila['grupo']}" if fila.get("grupo") else "Sin grupo"]
        detalle += [f"Aula {fila['aula']}" if fila.get("aula") else "Sin aula"]
        self.detalle = QLabel(" · ".join(detalle), objectName="fila_detalle", wordWrap=True)
        self.detalle.setTextFormat(Qt.PlainText)
        datos = QVBoxLayout()
        datos.setSpacing(2)
        datos.addWidget(self.docente)
        datos.addWidget(self.detalle)

        self.chip = QLabel("", objectName="chip_estado")
        self.chip.setAlignment(Qt.AlignCenter)
        self.chip.setMinimumWidth(104)
        self.chip.setFixedHeight(30)
        self.botones: dict[str, QPushButton] = {}
        caja_botones = QHBoxLayout()
        caja_botones.setSpacing(6)
        for estado, texto, icono in BOTONES:
            b = QPushButton(f"{icono} {texto}", objectName=f"btn_{estado}")
            b.setCheckable(True)
            b.setMinimumHeight(40)
            b.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
            b.setToolTip(f"Registrar «{texto}» en esta hora")
            b.clicked.connect(lambda _c=False, e=estado: self.elegir(e))
            b.setVisible(self.puede)
            self.botones[estado] = b
            caja_botones.addWidget(b)
        self.boton_nota = QPushButton("Observación", objectName="btn_secundario")
        self.boton_nota.setToolTip("Escribir una observación de esta hora")
        self.boton_nota.clicked.connect(self.mostrar_observacion)
        self.boton_justificante = QPushButton("Justificante", objectName="btn_secundario")
        self.boton_justificante.setToolTip("Adjuntar o ver documentos de esta hora")
        self.boton_justificante.clicked.connect(self.abrir_justificante)
        self.boton_mas = QPushButton("Más…", objectName="btn_secundario")
        self.boton_mas.setToolTip("Asistencia parcial, excepciones e historial")
        self.boton_mas.clicked.connect(self.mas_opciones)
        for b in (self.boton_nota, self.boton_justificante, self.boton_mas):
            b.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        self.boton_nota.setVisible(self.puede)

        # Segunda línea: datos que pide un estado, observación y aviso de guardado.
        self.editor = QWidget()
        capa_editor = QHBoxLayout(self.editor)
        capa_editor.setContentsMargins(0, 0, 0, 0)
        self.instruccion = QLabel("", objectName="fila_instruccion")
        self.entrada = QTimeEdit(displayFormat="HH:mm")
        self.entrada.setAccessibleName("Hora real de llegada")
        self.motivo_justificacion = QLineEdit(placeholderText="Motivo de la justificación")
        self.motivo_correccion = QLineEdit(
            placeholderText="Motivo del cambio (obligatorio, queda en el historial)"
        )
        self.boton_guardar = QPushButton("Guardar", objectName="primario")
        self.boton_cancelar = QPushButton("Cancelar")
        for w in (
            self.instruccion,
            self.entrada,
            self.motivo_justificacion,
            self.motivo_correccion,
            self.boton_guardar,
            self.boton_cancelar,
        ):
            capa_editor.addWidget(w)
        capa_editor.setStretch(2, 1)
        capa_editor.setStretch(3, 1)
        capa_editor.addStretch(0)
        self.entrada.setFixedWidth(110)
        for b in (self.boton_guardar, self.boton_cancelar):
            b.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.editor.hide()

        self.observacion = QLineEdit(placeholderText="Observación (opcional). Enter para guardar")
        self.observacion.setAccessibleName("Observación de esta hora")
        self.observacion.hide()
        self.aviso = QLabel("", objectName="fila_aviso", wordWrap=True)
        self.aviso.setTextFormat(Qt.PlainText)
        self.aviso.hide()

        rejilla = QGridLayout(self)
        rejilla.setContentsMargins(14, 10, 14, 10)
        rejilla.setHorizontalSpacing(14)
        rejilla.setVerticalSpacing(6)
        rejilla.addWidget(hora, 0, 0, 2, 1)
        rejilla.addLayout(datos, 0, 1)
        rejilla.addWidget(self.chip, 0, 2, Qt.AlignVCenter)
        rejilla.addLayout(caja_botones, 0, 3)
        extras = QHBoxLayout()
        extras.setSpacing(6)
        for b in (self.boton_nota, self.boton_justificante, self.boton_mas):
            extras.addWidget(b)
        rejilla.addLayout(extras, 0, 4)
        rejilla.addWidget(self.editor, 1, 1, 1, 4)
        rejilla.addWidget(self.observacion, 2, 1, 1, 4)
        rejilla.addWidget(self.aviso, 3, 1, 1, 4)
        rejilla.setColumnStretch(1, 1)

        self.boton_guardar.clicked.connect(self.guardar_editor)
        self.boton_cancelar.clicked.connect(self.cerrar_editor)
        for campo in (self.motivo_justificacion, self.motivo_correccion):
            campo.returnPressed.connect(self.guardar_editor)
        self.observacion.returnPressed.connect(self.guardar_observacion)
        self.observacion.textEdited.connect(lambda *_: self.vista.cambio_en_filas())
        self.actualizar()

    # --- estado visual ---------------------------------------------------------------

    @property
    def registro(self) -> dict | None:
        return self.fila.get("asistencia")

    def bloqueo(self) -> str:
        """Motivo por el que no se puede capturar en esta fila (vacío si se puede)."""
        f = self.fila
        if f.get("fuera_de_programacion"):
            return "Captura fuera del programa actual: consúltala en la vista detallada."
        if f.get("bloqueada_por_registro_previo") and not self.registro:
            return "Hay una captura anterior que se traslapa con esta hora: revisa el historial."
        if not f.get("dia_habil", True) and not self.registro:
            return "Día inhábil o suspendido: una excepción se registra en «Más…»."
        return ""

    def actualizar(self) -> None:
        estado = self.fila["estado"]
        self.chip.setText(ETIQUETAS.get(estado, estado))
        self.chip.setProperty("estado", estado)
        self.setProperty("estado", estado)
        for w in (self.chip, self):
            w.style().unpolish(w)
            w.style().polish(w)
        bloqueo = self.bloqueo()
        futura = str(self.fila["fecha"]) > date.today().isoformat()
        for clave, b in self.botones.items():
            b.setChecked(clave == estado)
            b.setProperty("activo", clave == estado)
            b.style().unpolish(b)
            b.style().polish(b)
            b.setEnabled(
                self.puede
                and not bloqueo
                and not self.ocupada
                and (not futura or clave == "justificado")
            )
        self.boton_justificante.setVisible(
            self.registro is not None
            and estado in ("justificado", "parcial")
            and self.vista.usuario.puede("documentos.ver")
        )
        self.boton_nota.setEnabled(self.puede and not self.ocupada and not bloqueo)
        texto_obs = (self.registro or {}).get("observaciones") or ""
        if texto_obs and not self.observacion.isModified():
            self.observacion.setText(texto_obs)
            self.observacion.show()
        if bloqueo and not self.aviso.isVisible():
            self.mostrar_aviso(bloqueo, "informacion")

    def mostrar_aviso(self, texto: str, tipo: str = "exito") -> None:
        self.aviso.setText(texto)
        self.aviso.setProperty("tipo", tipo)
        self.aviso.style().unpolish(self.aviso)
        self.aviso.style().polish(self.aviso)
        self.aviso.setVisible(bool(texto))

    def tiene_cambios(self) -> bool:
        """Datos escritos que aún no se guardan (editor abierto u observación editada)."""
        if self.estado_editor:
            return True
        guardada = (self.registro or {}).get("observaciones") or ""
        return self.observacion.isModified() and self.observacion.text().strip() != guardada

    # --- captura ---------------------------------------------------------------------

    def elegir(self, estado: str) -> None:
        if not self.puede or self.ocupada or self.bloqueo():
            self.actualizar()
            return
        actual = self.fila["estado"]
        if self.registro and estado == actual:
            self.actualizar()  # ya está así: nada que guardar
            return
        if self.registro is None and estado in ("asistio", "falto"):
            self.cerrar_editor()
            self.enviar({"estado": estado})
            return
        self.abrir_editor(estado)

    def abrir_editor(self, estado: str) -> None:
        self.estado_editor = estado
        correccion = self.registro is not None
        nombre = ETIQUETAS[estado]
        if correccion:
            self.instruccion.setText(f"Cambiar a «{nombre}».")
        elif estado == "retardo":
            self.instruccion.setText("Hora real de llegada:")
        elif estado == "justificado":
            self.instruccion.setText("Justificado.")
        else:
            self.instruccion.setText(f"Registrar «{nombre}».")
        self.entrada.setVisible(estado == "retardo")
        if estado == "retardo":
            self.entrada.setTime(llegada_sugerida(self.fila, date.today(), datetime.now()))
        self.motivo_justificacion.setVisible(estado == "justificado")
        if estado == "justificado" and correccion:
            self.motivo_justificacion.setText(self.registro.get("justificacion") or "")
        self.motivo_correccion.setVisible(correccion)
        self.editor.show()
        for b in self.botones.values():
            b.setChecked(b.objectName() == f"btn_{estado}")
        self.mostrar_aviso("", "exito")
        foco = (
            self.motivo_correccion
            if correccion
            else self.entrada
            if estado == "retardo"
            else self.motivo_justificacion
        )
        foco.setFocus()
        self.vista.cambio_en_filas()

    def cerrar_editor(self) -> None:
        self.estado_editor = None
        self.editor.hide()
        self.motivo_justificacion.clear()
        self.motivo_correccion.clear()
        self.actualizar()
        self.vista.cambio_en_filas()

    def keyPressEvent(self, evento) -> None:  # noqa: N802 (nombre de Qt)
        if evento.key() == Qt.Key_Escape and self.estado_editor:
            self.cerrar_editor()
            return
        if evento.key() in (Qt.Key_Return, Qt.Key_Enter) and self.estado_editor:
            self.guardar_editor()
            return
        super().keyPressEvent(evento)

    def guardar_editor(self) -> None:
        estado = self.estado_editor
        if not estado:
            return
        datos: dict = {"estado": estado}
        if estado == "retardo":
            datos["hora_entrada"] = self.entrada.time().toString("HH:mm")
        if estado == "justificado":
            motivo = self.motivo_justificacion.text().strip()
            if not motivo:
                self.mostrar_aviso("Escribe el motivo de la justificación.", "error")
                self.motivo_justificacion.setFocus()
                return
            datos["justificacion"] = motivo
        if self.registro is not None:
            motivo = self.motivo_correccion.text().strip()
            if len(motivo) < 5:
                self.mostrar_aviso(
                    "Escribe el motivo del cambio (al menos 5 letras): queda en el historial.",
                    "error",
                )
                self.motivo_correccion.setFocus()
                return
            datos["motivo"] = motivo
        self.enviar(datos)

    def enviar(self, datos: dict) -> bool:
        """Guarda en el servidor (registro nuevo o corrección) y actualiza solo esta fila."""
        self.ocupada = True
        self.actualizar()
        f = self.fila
        texto_obs = self.observacion.text().strip()
        try:
            if self.registro is None:
                if texto_obs:
                    datos = {**datos, "observaciones": texto_obs}
                respuesta = self.vista.api.post(
                    "/asistencias/horas",
                    {
                        **datos,
                        "docente_id": f["docente_id"],
                        "fecha": str(f["fecha"]),
                        "bloque_id": f["bloque_id"],
                        "programado_inicio": f["programado_inicio"],
                    },
                )
            else:
                respuesta = self.vista.api.patch(f"/asistencias/horas/{self.registro['id']}", datos)
        except ErrorApi as error:
            self.ocupada = False
            self.actualizar()
            detalle = f" {error.problemas[0]}" if error.problemas else ""
            self.mostrar_aviso(f"No se guardó: {error}.{detalle}", "error")
            return False
        self.ocupada = False
        f["asistencia"] = respuesta
        f["estado"] = respuesta["estado"]
        f["minutos"] = minutos_de(f, respuesta)
        self.estado_editor = None
        self.editor.hide()
        self.motivo_justificacion.clear()
        self.motivo_correccion.clear()
        self.observacion.setModified(False)
        self.actualizar()
        cambio = "Corrección guardada" if "motivo" in datos else "Guardado"
        hora = datetime.now().strftime("%H:%M")
        extra = ""
        if f["estado"] == "justificado" and self.vista.usuario.puede("documentos.ver"):
            extra = " Puedes adjuntar el justificante con el botón «Justificante»."
        self.mostrar_aviso(f"✓ {cambio}: {ETIQUETAS[f['estado']]} · {hora}.{extra}", "exito")
        self.vista.fila_guardada(self)
        return True

    # --- observación, justificante y opciones avanzadas ---------------------------------

    def mostrar_observacion(self) -> None:
        self.observacion.show()
        self.observacion.setFocus()

    def guardar_observacion(self) -> None:
        texto = self.observacion.text().strip()
        if self.registro is None:
            # Se guardará junto con el registro de esta hora.
            self.mostrar_aviso(
                "La observación se guardará al registrar la asistencia de esta hora.",
                "informacion",
            )
            return
        if texto == (self.registro.get("observaciones") or ""):
            self.observacion.setModified(False)
            return
        if self.enviar({"observaciones": texto, "motivo": MOTIVO_OBSERVACION}):
            self.mostrar_aviso(f"✓ Observación guardada · {datetime.now():%H:%M}.", "exito")

    def abrir_justificante(self) -> None:
        if self.registro is not None:
            self.vista.abrir_documentos_de(self.fila)

    def mas_opciones(self) -> None:
        self.vista.mas_opciones(self.fila)
