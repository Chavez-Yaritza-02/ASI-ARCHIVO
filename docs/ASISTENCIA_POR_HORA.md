# Ampliación de Etapa 4: asistencia por hora de clase

## Revisión del estado anterior

La Etapa 5 validada (`f305e6e`, PR #6) conservaba la unidad de la Etapa 4:
`docente + fecha + turno`. Evidencia: `Asistencia.__table_args__` en
`server/app/models/asistencia.py`, agrupación `programacion()` en
`server/app/services/bitacora.py`, pantalla `VistaBitacora` y los reportes originales.
El modelo indicaba expresamente «asistencia general, no por clase».

| Requisito | Antes | Con esta ampliación |
|---|---|---|
| Registro independiente por hora | No | Una captura independiente por tramo programado |
| Asistir a una hora y faltar a otra el mismo día | No dentro del mismo turno | Sí, estados independientes |
| Asistencia parcial | No como cantidad de horas cumplidas | Entrada/salida y minutos exactos dentro del tramo |
| PDF/Excel con horas programadas, cumplidas, faltantes y justificadas | No; contaban registros por turno | Sí; incluyen también pendientes y suspensiones |
| Captura gráfica por hora | No | Pantalla principal «Asistencia por hora» |
| Auditoría y duplicados | Sí, por turno | Sí, también por hora y con protección de concurrencia |

La bitácora y reportes anteriores siguen accesibles para consultar y corregir su
información conforme a los permisos existentes. Sus registros **no acreditan horas**
y no se convierten ni se copian automáticamente a la tabla nueva.

## Unidad de captura y reglas de cálculo

- Se usa exclusivamente la versión con vigencia confirmada para la fecha, incluyendo
  versiones históricas cuando corresponden. Una fecha desconocida nunca se infiere.
- Un bloque de 07:00–09:00 produce las filas 07:00–08:00 y 08:00–09:00. Un bloque
  de 07:30–09:00 produce 07:30–08:30 y 08:30–09:00. El último tramo conserva su duración
  real. Las horas de los horarios deben tener precisión de minutos; si tienen segundos,
  se solicita revisar el horario en vez de redondearlo.
- Los bloques pueden ser materias u otras actividades, identificadas por tipo. La pantalla
  y los reportes permiten elegir **Solo clases**, **Otras actividades** o ambas.
- El turno se determina por el inicio de cada tramo, con la división existente de las 14:00.
- La unidad contable es el minuto. Una hora decimal equivale a 60 minutos; se muestran
  cuatro decimales para fracciones periódicas, conservando siempre el total exacto en minutos.
- Un registro sin horas reales y estado **asistió** es una confirmación manual de cumplimiento
  completo de ese tramo. Si se proporcionan horas para ese estado, deben coincidir con el tramo.
- **Falta:** cero minutos cumplidos o justificados; no admite horas de presencia.
- **Justificado:** todo el tramo justificado, con motivo obligatorio y sin horas de presencia.
- **Parcial:** entrada y salida obligatorias dentro del tramo; el intervalo debe ser menor
  que el tramo completo. Puede especificarse cuántos minutos restantes están justificados,
  con motivo. Presencia más justificación nunca puede exceder la duración programada.
- **Retardo:** entrada posterior al inicio, dentro del tramo; salida opcional, hasta el fin.
  Se computan los minutos efectivamente cumplidos, no una hora completa por tolerancia.
  La tolerancia administrativa sigue disponible como sugerencia de clasificación y no
  suma minutos de presencia ni cambia estados automáticamente.
- **Pendiente:** aún no existe captura; sus minutos pendientes nunca se cuentan como falta.
- **Suspensión/inhábil:** sin captura autorizada, sus minutos quedan suspendidos y no exigibles.
  Una excepción explícita exige `asistencia.corregir`. Las capturas ya registradas se
  conservan aunque el calendario sea corregido después; no se reescriben sus evidencias.

Identidades para el conjunto filtrado de horas del programa consultado:

```text
programadas = exigibles + suspendidas
exigibles = cumplidas + faltantes + justificadas + pendientes
```

«Faltantes» significa tiempo no cumplido ni justificado de una hora con captura explícita
(falta, parcial o retardo). No equivale a asignar automáticamente el estado «faltó».

## Conservación, duplicados y correcciones

La tabla `asistencia_hora` conserva docente, fecha, periodo, horario, bloque, tramo,
materia/actividad, grupo, aula y nombres al momento de registrar. Las correcciones
solo cambian el estado, las evidencias de presencia, observaciones y justificación;
no reasignan silenciosamente la captura a una versión o clase distinta.

Una restricción única por docente + fecha + inicio impide duplicados en PostgreSQL.
El servicio rechaza además intervalos superpuestos y bloquea la fila del docente,
usando el mismo bloqueo que la confirmación de horarios, para serializar capturas
concurrentes y evitar carreras con cambios de vigencia.

Si una corrección de vigencia modifica el programa correspondiente a una fecha:

- La captura original se muestra en **Capturas fuera del programa actual**, con sus
  valores originales, y tiene totales separados.
- La programación que ahora corresponde a la fecha se calcula de nuevo; no recibe
  los estados de la captura anterior.
- Una hora nueva que se traslape con una captura previa queda bloqueada para registro.
  Se requiere revisar la vigencia y su evidencia, sin crear registros duplicados ni borrar
  la captura previa. Esta entrega no automatiza una reasignación histórica.

Toda captura y corrección queda en la auditoría inmutable bajo `asistencia_hora`.
Corregir exige motivo; días anteriores y capturas por excepción requieren
`asistencia.corregir`. No se registran asistencias a futuro salvo justificaciones,
y los periodos cerrados quedan de solo lectura.

## API y permisos

| Ruta | Uso | Permisos |
|---|---|---|
| `GET /bitacora/horas?fecha` | Horas calculadas, capturas, totales y avisos | `asistencia.ver` |
| `POST /asistencias/horas` | Captura de una hora programada | `asistencia.registrar` |
| `PATCH /asistencias/horas/{id}` | Corrección con motivo | `asistencia.registrar`, más autorización cuando aplica |
| `GET /asistencias/horas/{id}/historial` | Cambios por registro | `asistencia.ver` |
| `GET /bitacora/horas/exportar?fecha&formato=pdf\|xlsx` | Reporte del día | `asistencia.ver` + `reportes.generar` |
| `GET /bitacora/horas/reporte?desde&hasta&formato=pdf\|xlsx` | Reporte de hasta 93 días | mismos permisos de exportación |

Consulta y reportes admiten filtros por docente, turno, estado y tipo de actividad.
Los totales corresponden al conjunto filtrado. Las vigencias desconocidas se excluyen
y se advierten, sin calcular horas supuestas. Los registros por turno se identifican
como legados sin convertir. Los campos de identidad, minutos cumplidos calculados y
copias del programa no se pueden inyectar en la captura o corrección por API.

## Aplicación gráfica y reportes

«Asistencia por hora» es la primera sección del menú. Selecciona fecha, docente, turno,
estado y tipo; cada fila permite registrar/corregir y abrir su historial. El formulario
ofrece estado parcial, entrada, salida y minutos justificados. Los botones de captura
y exportación se muestran según permisos, que la API vuelve a verificar.

La pantalla muestra resumen en horas y minutos, capturas fuera del programa actual y
avisos por vigencias desconocidas o registros anteriores superpuestos. Exporta el día
seleccionado o un rango de fechas en PDF y Excel.

Ambos formatos muestran los totales de horas y minutos y el detalle por tramo. Excel
incluye hojas de resumen, acumulados por docente y capturas fuera de programación.
PDF incluye el historial fuera del programa en una sección separada. Se conservan los
cargos de firma «Asistente de Jefatura» y «Jefatura de Electromecánica», sin nombres fijos.
El PDF escapa texto de catálogos y notas; Excel escribe los textos como cadenas literales.

## Migración y comprobaciones

`a4h001`, posterior a `e5a001`, agrega únicamente tabla, índices y restricciones. No
modifica migraciones publicadas, horarios, vigencias, asistencias por turno ni auditoría.
No convierte información anterior. El downgrade se bloquea para evitar eliminar capturas.
No se aplica a bases con datos reales durante este desarrollo.

Pruebas principales en `server/tests/test_asistencia_hora.py`:

- `test_cada_hora_es_independiente_y_pendiente_no_es_falta`.
- `test_asiste_una_hora_y_falta_otra_del_mismo_dia`.
- `test_parciales_y_justificaciones_en_minutos_exactos`.
- `test_reportes_pdf_excel_calculan_horas_y_mantienen_firmas`.
- `test_duplicados_rechazados_en_api_y_base` y `test_dos_capturas_concurrentes_solo_crean_una`.
- `test_migracion_aditiva_no_convierte_ni_modifica_registros`.
- Casos de vigencias, permisos, suspensiones, fechas futuras y protección de exportaciones.

Las seis pruebas de `server/tests/test_interfaz_asistencia_hora.py` ejercitan captura,
parciales, corrección, historial, permisos, exportaciones y menú con Qt real contra API y
PostgreSQL ficticios. La comprobación portable de `client/tests/test_consultas_escritorio.py`
incluye esta pantalla y corre también en los jobs de Windows y macOS.

La base sigue siendo exclusivamente `asi_archivo_pytest`, con todas las protecciones de
la Etapa 5 activas. La Etapa 6 permanece sin comenzar.

### Resultado de validación local

- **217 pruebas aprobadas** en macOS: las 173 existentes más 44 nuevas.
- Las 13 pruebas portables del cliente incluyen el arranque de la nueva pantalla Qt,
  sin base de datos, además de los flujos horarios integrados con PostgreSQL.
- Ruff y formato aprobados en 109 archivos Python; `git diff --check` sin errores.
- Revisión de publicación: sin archivos institucionales, tokens o claves privadas;
  no se modifican migraciones publicadas ni se añaden dependencias.
- Las pruebas recrean solamente el esquema de `asi_archivo_pytest`; no se ejecutan
  migraciones en la principal, la de desarrollo ni la aislada de OCR.
