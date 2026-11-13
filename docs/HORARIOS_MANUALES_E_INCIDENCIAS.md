# Captura manual de horarios e importación de incidencias desde Excel

**Rama:** `horarios-manuales-e-incidencias`, creada desde `etapa3-aplicacion-local`.
No tiene merge ni PR. `main` y las bases reales, de revisión y de demostración no se
modificaron. Las incidencias reales **no** se importaron a ninguna base. Todas las pruebas
usan datos ficticios.

## 1. Qué existía y qué se agregó

| Necesidad | Ya existía | Se agregó |
|---|---|---|
| Horarios versionados; borrador → vigente → histórico | Sí (servidor y ventana) | — |
| Traslapes y clases repetidas en un mismo horario | Sí, al guardar (servidor) | Aviso **antes** de guardar: «ya está» o «¿reemplazar?» |
| Aula o grupo ocupados por otro docente | Sí, como advertencia | — |
| Elegir docente, materia, grupo y aula | Sí (doble clic en la cuadrícula) | Ventana **Agregar clase…** con día, inicio y fin |
| Editar, eliminar y consultar | Solo por celdas | **Editar clase…**, **Eliminar clase** y pestaña **Lista de clases** |
| Agregar profesores | Solo en el catálogo | **Nuevo docente…** en Horarios |
| Cambiar de semestre conservando la asistencia | Sí: periodos y copia del horario en cada registro | **Copiar clases del semestre anterior**, con los grupos pendientes de asignar |
| OCR y captura manual sobre los mismos horarios | Sí: las dos crean versiones del mismo docente y periodo | Prueba que lo confirma |
| Importar faltas y salidas desde Excel | No | Todo lo de la sección 3 |

## 2. Captura manual de horarios (Horarios › Por docente)

- **Agregar clase…**: día, hora de inicio, hora de fin, materia o actividad, grupo y aula.
  Se pueden agregar varias el mismo día.
- **Una clase repetida** no se duplica. Si las horas ya tienen otra clase, se pregunta
  antes de reemplazarla. Al guardar, el servidor vuelve a validar.
- **Corregir una versión vigente** crea una versión nueva (borrador). La vigente no
  cambia hasta confirmar la nueva.
- **Semestre nuevo**: «Nueva versión» en el periodo nuevo ofrece copiar las clases del
  anterior. Los grupos quedan con la letra pendiente de asignar, y el horario anterior y
  su asistencia no se tocan.

## 3. Importación de incidencias (Asistencias › Importar incidencias)

**Tablas nuevas.** Son la zona de revisión de las incidencias, en la migración aditiva
`i7a001`:

- `importacion_incidencias`: guarda un archivo por huella SHA-256, así que el mismo
  archivo no se registra dos veces.
- `incidencia_importada`: una fila del Excel. Guarda el texto original como evidencia, los
  valores corregidos, las horas elegidas y su estado: pendiente, importada o descartada.

**Cómo funciona:**

1. **Leer** el Excel no registra asistencia. Las columnas se reconocen por su encabezado:
   FECHA, DOCENTE/PROFESOR/NOMBRE, INCIDENCIA/TIPO, HORA y OBSERVACIONES/MOTIVO.
   - Las fechas se leen como día/mes/año.
   - Las horas se leen en formatos como «7:00 p. m.».
2. **Docentes**: se relacionan sin importar el orden de las palabras.
   - Si coinciden todas las palabras, se asigna.
   - Si es parecido, queda «sugerido» y hay que confirmarlo.
   - Si es ambiguo o no aparece, no se asigna nada.
3. **Vista previa editable** con los problemas de cada fila:
   - docente no encontrado o sugerido;
   - fecha ilegible, futura, fuera de periodo o de un periodo cerrado;
   - tipo no claro, salida sin hora o justificación sin motivo;
   - horas ya registradas, día inhábil;
   - posible duplicado (en el mismo archivo o en otro).
4. **Horas exactas**: se muestra el horario del docente ese día y el usuario marca las
   horas que no se cumplieron. **Ninguna se marca sola.** En una salida anticipada se
   sugieren las horas posteriores a la salida, pero no se eligen.
5. **Qué se registra por cada hora:**
   - **Falta**: «falta», o «justificada» si tiene motivo.
   - **Salida anticipada**: las horas que empiezan después de la salida, como falta. La
     hora en que salió, como «parcial» (presente desde el inicio de esa hora hasta la
     salida).
   - En todos los casos, la observación queda como «Salida anticipada a las HH:MM,
     reportada en Excel (archivo, fila N)» o «Falta reportada…».
6. **Importar**: solo las filas marcadas, y solo si no tienen problemas. Es **todo o
   nada**: si una hora falla, no se guarda ninguna. Las filas sin horas o sin datos
   quedan **pendientes**.
7. **Justificante** opcional del archivo digital. Se vincula a cada hora importada, en la
   misma transacción.

**Caso especial** (probado con un equivalente ficticio): el docente sale a las 19:00 y su
jornada termina a las 20:00. Solo se registra la hora 19:00–20:00. Las anteriores siguen
pendientes; no se marcan como falta.

**Seguridad:**

- Nunca se sobrescribe una asistencia existente: esa hora se informa y se corrige en
  Asistencia por hora.
- Cada lectura, corrección, descarte, recuperación e importación queda en la auditoría.
- No hay forma de borrar filas: se descartan con motivo y se pueden recuperar.
- Importar requiere `asistencia.corregir`, porque son días pasados.

## 4. Base local y PostgreSQL

- **PostgreSQL:** se agrega la migración `i7a001`, que solo crea dos tablas.
  `/sistema/estado` exige esa versión. **No se aplicó** a la base de revisión ni a la de
  demostración.
- **SQLite (aplicación local):**
  - Una base nueva se crea ya en `i7a001`.
  - Una base de la etapa 3 (`e6a001`) se actualiza **solo agregando** las dos tablas
    vacías, en una transacción, después de comprobar versión, protecciones e integridad.
  - Cualquier otra diferencia detiene la aplicación sin modificar nada.

## 5. Resultados de las pruebas

| Suite | Resultado |
|---|---|
| SQLite (aplicación local) | **474 aprobadas**, 6 omitidas (propias de PostgreSQL) |
| PostgreSQL | **470 aprobadas**, 10 omitidas (propias de la base local) |
| Cliente (sin base de datos) | **37 aprobadas** |
| Ruff (estilo) | Sin observaciones |

Pruebas nuevas:

- **`test_incidencias_excel.py`**, que corre en las dos bases:
  - lectura sin registrar nada y el mismo archivo dos veces;
  - archivos inválidos, que no guardan nada, y permisos;
  - el caso especial de la salida anticipada y la salida a mitad de hora;
  - filas sin horas, que quedan pendientes, y la importación todo o nada;
  - que no se sobrescribe lo ya registrado, los duplicados y el descarte;
  - la justificación con motivo, las correcciones auditadas y persistentes, y el día
    inhábil;
  - la lectura de fechas, horas, tipos y nombres.
- **`test_interfaz_horarios_e_incidencias.py`**, sobre las ventanas reales:
  - nuevo docente;
  - agregar varias clases, clase repetida y traslape;
  - guardar, volver a abrir, editar sobre una versión vigente y eliminar;
  - choque de aula o grupo con otro docente;
  - copiar clases al semestre nuevo;
  - vista previa, revisión e importación;
  - archivo inválido.
- **`test_sqlite_compatibilidad.py`**: actualización aditiva de una base local anterior y
  bases inconsistentes, que no se tocan.
- **De punta a punta, local y sin red** (`test_modo_local.py`): importa una falta del
  Excel (solo la hora elegida), cierra, otro proceso la vuelve a abrir y la encuentra, y
  el mismo archivo no se duplica.

## 6. Limitaciones pendientes

- La cuadrícula y la ventana «Agregar clase» usan **horas completas** (07:00 a 23:00),
  como los horarios institucionales y el OCR. Las clases que empiezan a la media hora no
  se capturan desde la ventana.
- Si el Excel se **vuelve a guardar**, su huella cambia y se registra como un archivo
  nuevo. Aun así, sus filas aparecen como «posible duplicado» o «ya tiene registro», y
  no se pueden crear horas repetidas.
- El formato del Excel real no se ha revisado, para no leer datos reales sin
  autorización. Si sus encabezados son otros, al cargarlo se muestra qué encabezados se
  leyeron, sin guardar nada, y se agregan al lector. Las fechas de texto se leen como
  día/mes/año.
- En una **salida a mitad de una hora**, esa hora se registra como parcial, presente
  desde el inicio de la hora hasta la salida. Se muestra antes de importar y esa hora se
  puede desmarcar.
- Las filas ya importadas se corrigen en **Asistencia por hora**, con motivo e historial,
  no en la pantalla de importación.
- Un docente que no está en el catálogo no se crea automáticamente. Se agrega con
  «Nuevo docente…» o en el catálogo, y luego se elige en la fila.
