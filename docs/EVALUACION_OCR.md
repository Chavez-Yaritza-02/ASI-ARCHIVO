# Etapa 1b — Evaluación de OCR de horarios docentes

> Fecha: 2026-11-04. Archivo evaluado: `HORARIOS_POR_MAESTRO.zip` (26 PDF).
> Los documentos se identifican como "Doc 01 … Doc 26" (orden alfabético del ZIP)
> para no incluir datos personales en el repositorio.

## 1. Resumen

| Resultado | Valor |
|---|---|
| PDF procesados | 26 de 26 (36 páginas) |
| Celdas de horario evaluadas (una por hora) | 1 080 |
| Día y hora correctos | **100%** |
| Grupo | **100%** |
| Asignatura/actividad | **97.8%** |
| Aula (sin catálogo / con catálogo) | **97.3% / 99.4%** |
| Nombre del docente (QR y, si falta, OCR) | **100%** |
| Celdas falsas (firmas o sellos leídos como clase) | **0** |
| Errores que pasarían sin marcar (con catálogo) | **0** |
| Celdas que se marcarían para revisión manual | 46 (4.3%) |
| Tiempo de proceso de los 26 PDF | ≈ 11 s |

**Conclusión:** la importación desde PDF escaneado es viable siempre que pase por una
vista previa editable. Para el día, la hora y el grupo, el OCR casi no necesita
corrección. El aula y la actividad necesitan un catálogo de referencia y la revisión de
las celdas marcadas.

## 2. Cómo se hizo

1. Se confirmó que el ZIP contiene exactamente 26 PDF (más un `LISTA_ARCHIVOS.txt`).
2. Se trabajó con una **copia temporal** fuera del repositorio. Al terminar, la huella
   SHA-256 del ZIP original seguía igual: no se modificó.
3. Todo se procesó localmente (Tesseract 5 + PyMuPDF + OpenCV). No se envió nada a
   servicios externos.
4. **Transcripción verificada:** cada una de las 36 páginas se revisó contra la imagen
   y se transcribió a mano. Para comprobarla se comparó el número de celdas transcritas
   con el total de horas que trae el código QR de cada página: coincidió en las
   **34 de 34** páginas con QR legible.
5. La herramienta [herramientas/ocr_prueba/evaluar.py](../herramientas/ocr_prueba/evaluar.py)
   compara la extracción contra esa transcripción, celda por celda.

La transcripción y los resultados con nombres reales **no** están en el repositorio.

## 3. Hallazgos sobre los documentos

- **Los 26 PDF son escaneados**: no tienen texto digital. Cada página es una imagen de
  200 DPI en tamaño carta, así que todo depende del OCR.
- **Formato único:** todos usan la misma plantilla institucional:
  - Encabezado con unidad, docente, área, vigencia, periodo, nómina, fecha y versión.
  - Cuadrícula de 07:00 a 23:00, de lunes a sábado.
  - Cada celda dice "Actividad / Grupo: X Aula: Y" o "Actividad / Aula: Y".
- **Código QR con los datos del encabezado.** Ejemplo ficticio:
  `ZAPOPAN,AGOSTO - DICIEMBRE 2026,NOMBRE,NÓMINA,FECHA,VIGENCIA,VERSIÓN,…,MAT[25],TOT[40]`.
  Se leyó en 34 de 36 páginas. Sus ventajas:
  - Da el encabezado **sin errores**.
  - `TOT[n]` coincide con el número de horas ocupadas en la cuadrícula, así que sirve
    como control automático de que se leyeron todas las celdas.
- **Documentos de varias páginas** (8 de 26). No son una sola hoja dividida, sino
  **copias o versiones del mismo horario**:
  - Copias idénticas: Doc 01, 17, 21 y 24.
  - Versiones distintas: Doc 03, 16, 22 y 25. Ejemplo: en el Doc 03 la v2 movió una
    clase del lunes a las 14:00 al jueves a las 7:00.
  - Doc 16: la página "v2" tiene una fecha **anterior** a la "v1". El número de versión
    no basta para saber cuál está vigente; el usuario debe confirmarlo.
- **Firmas, sellos y anotaciones a mano** ("Recibí original…") que a veces caen sobre la
  cuadrícula, sobre todo en la columna del sábado.
- **El sábado sí se usa** (Doc 25 v2). No se puede ignorar esa columna.

## 4. Evolución del método

| Versión | Cambio | Día/hora | Actividad | Grupo | Aula* |
|---|---|---|---|---|---|
| 1 | OCR por celda, modelo en español | 96.4% | 90.3% | 94.8% | 81.0% |
| 2 | OCR por columna completa; día buscado solo en la fila de encabezados; sin diccionario | 100% | 96.0% | 99.6% | 85.8% |
| 3 | Modelo de OCR en inglés para las celdas | 100% | 97.5% | 100% | 97.3% |
| 4 | Limpieza de restos de las líneas de la cuadrícula | 100% | 97.8% | 100% | 97.3% |
| 4 + catálogo | Corrección con catálogo verificado de aulas y actividades | 100% | 97.8% | 100% | 99.4% |

\* Aula comparada considerando O=0 e I=1, que en esta tipografía son indistinguibles.

Lecciones de cada cambio:

- **OCR por columna en lugar de por celda.** Recortar cada celda cortaba texto cuando
  una fila era más alta (celdas de 3 líneas) o la etiqueta de hora se detectaba unos
  píxeles corrida. Leer la columna completa y asignar cada línea a la fila donde empieza
  eliminó esos errores. También es 30 veces más rápido.
- **Encabezados de día buscados solo en la línea de "HORAS".** En el Doc 16 el apellido
  del docente, muy parecido a "MARTES", se tomaba como encabezado de columna y desplazaba
  toda la cuadrícula una columna.
- **Modelo en inglés.** El modelo en español "corrige" claves hacia palabras ("M05" se
  vuelve "MOS") y lee "A" como "Á". El modelo en inglés lee mejor las claves de aula.

## 5. Precisión por campo (resultado final)

| Campo | Sin catálogo | Catálogo automático | Catálogo verificado |
|---|---|---|---|
| Día y hora | 100.0% (1080/1080) | 100.0% | 100.0% |
| Actividad (texto exacto) | 92.5% (999/1080) | 93.7% | 96.3% |
| Actividad (≈, mismo numeral) | 97.8% (1056/1080) | 97.8% | 97.8% |
| Grupo | 100.0% (1080/1080) | 100.0% | 100.0% |
| Aula (texto exacto) | 86.1% (930/1080) | 85.8% | 99.4% |
| Aula (O=0, I=1) | 97.3% (1051/1080) | 96.8% | 99.4% |

| Encabezado | Correctos | Precisión |
|---|---|---|
| Código QR leído | 34/36 | 94.4% |
| Nombre desde QR | 34/36 | 94.4% |
| Nombre desde OCR del encabezado | 34/36 | 94.4% |
| Nombre combinado (QR y, si falta, OCR) | 36/36 | 100% |
| Celdas leídas = horas del QR | 34/34 páginas con QR | 100% |

- **Catálogo automático:** se arma solo con las lecturas del OCR. No ayuda, porque a
  veces la lectura equivocada es la más frecuente.
- **Catálogo verificado:** simula tener ya en la base de datos las aulas y asignaturas
  reales. Es la opción recomendada (ver §8).

## 6. Resultados por documento

Aula = sin catálogo (O=0, I=1). Aula (cat.) = con catálogo verificado.

| Doc | Págs | Versiones | Celdas | Día/hora | Actividad | Grupo | Aula | Aula (cat.) | Revisión |
|---|---|---|---|---|---|---|---|---|---|
| 01 | 2 | v1 (copias) | 10 | 100% | 100% | 100% | 90% | 90% | 1 aula ilegible |
| 02 | 1 | v1 | 40 | 100% | 100% | 100% | 100% | 100% | 3 actividades ambiguas |
| 03 | 4 | v1 ×2, v2 ×2 | 152 | 100% | 100% | 100% | 98% | 100% | Elegir versión vigente |
| 04 | 1 | v1 | 25 | 100% | 100% | 100% | 88% | 88% | 3 aulas "L4.0" mal leídas |
| 05 | 1 | v1 | 32 | 100% | 100% | 100% | 100% | 100% | — |
| 06 | 1 | v1 | 30 | 100% | 100% | 100% | 97% | 100% | — |
| 07 | 1 | v1 | 4 | 100% | 50% | 100% | 100% | 100% | Numeral romano perdido |
| 08 | 1 | sin QR | 40 | 100% | 98% | 100% | 100% | 100% | QR ilegible; 1 actividad |
| 09 | 1 | v1 | 39 | 100% | 100% | 100% | 100% | 100% | 4 actividades ambiguas |
| 10 | 1 | v1 | 40 | 100% | 100% | 100% | 98% | 100% | — |
| 11 | 1 | v1 | 24 | 100% | 100% | 100% | 100% | 100% | 1 actividad ambigua |
| 12 | 1 | v1 | 40 | 100% | 95% | 100% | 95% | 98% | Numeral perdido; 1 aula |
| 13 | 1 | v1 | 40 | 100% | 90% | 100% | 100% | 100% | "Avan I" vs "Avan II" |
| 14 | 1 | v1 | 40 | 100% | 100% | 100% | 100% | 100% | — |
| 15 | 1 | v1 | 40 | 100% | 92% | 100% | 90% | 100% | Numeral perdido |
| 16 | 2 | v2, v1 | 50 | 100% | 100% | 100% | 100% | 98% | Elegir versión (fechas invertidas) |
| 17 | 2 | v1 (copias) | 36 | 100% | 100% | 100% | 97% | 100% | — |
| 18 | 1 | v1 | 39 | 100% | 100% | 100% | 100% | 100% | — |
| 19 | 1 | v1 | 35 | 100% | 100% | 100% | 100% | 100% | — |
| 20 | 1 | v1 | 20 | 100% | 100% | 100% | 100% | 100% | — |
| 21 | 2 | v1 (copias) | 60 | 100% | 85% | 100% | 93% | 98% | Numerales perdidos; 1 aula |
| 22 | 2 | sin QR, v2 | 74 | 100% | 100% | 100% | 100% | 99% | 1 pág. sin QR; elegir versión |
| 23 | 1 | v1 | 5 | 100% | 100% | 100% | 100% | 100% | — |
| 24 | 2 | v1 (copias) | 68 | 100% | 100% | 100% | 100% | 100% | — |
| 25 | 2 | v1, v2 | 80 | 100% | 96% | 100% | 100% | 100% | Elegir versión; 10 actividades |
| 26 | 1 | v1 | 17 | 100% | 100% | 100% | 47% | 100% | Aula "LQ" leída "LO" |

"Ambigua" significa que la lectura se parece a más de una asignatura del catálogo, por
lo que el sistema no la corrige solo y la deja para revisión.

## 7. Errores encontrados

| Tipo de error | Casos | ¿Se detecta solo? |
|---|---|---|
| Se pierde el numeral romano final ("Manufactura Avan **I**" → "Avan", "TERM.**I**" → "TERM.") | ~20 | Sí: con catálogo queda ambiguo y se marca |
| Aula "LQ" leída como "LO" | 13 | Sí: el catálogo la corrige |
| "L4.0" leída como "1.4.0", "4.0" o "14.0" | 6 | Sí: no coincide con el catálogo y se marca |
| "M05" leída como "MOS" o "M0S"; "B05" como "BOS" | 5 | Sí: el catálogo lo corrige |
| Prefijos de la línea de cuadrícula ("O1S." por "DIS.") | 3 | Sí: se marca |
| Aula no leída (celda muy clara) | 1 | Sí: aula vacía, se marca |
| QR ilegible | 2 páginas | Sí: se usa el nombre por OCR y se avisa que no hay total para verificar |
| Versiones múltiples en un PDF | 4 documentos | Sí: por versión y fecha del QR |

Con el catálogo verificado **no quedó ningún error sin marcar**: todo error restante
aparece como celda "por revisar" en la vista previa.

## 8. Recomendación para el importador (Etapa 3)

1. **Leer el encabezado del QR.** Usar el OCR del encabezado solo como respaldo cuando
   el QR no se pueda leer.
2. **Validar con `TOT` del QR** que el número de horas leídas coincide. Si no coincide,
   marcar la página completa.
3. **Usar el extractor por columnas** con el modelo `eng` y sin diccionario. Este
   prototipo pasaría a `server/app/importers/` con pruebas.
4. **Catálogos de aulas y asignaturas en la base de datos.** Son la pieza que lleva el
   aula de 97% a 99%. La primera importación se revisa a mano; lo confirmado alimenta el
   catálogo para los siguientes semestres.
5. **Corrección conservadora:** corregir solo si hay una única coincidencia en el
   catálogo. Si hay varias o ninguna, dejar el valor y marcar la celda.
6. **Vista previa editable** que muestre la imagen de cada celda junto al texto leído,
   resalte las celdas marcadas y no permita guardar mientras haya celdas sin revisar o
   el total no coincida.
7. **Versiones y duplicados:**
   - Agrupar las páginas de un PDF por versión y fecha del QR.
   - Descartar copias idénticas.
   - Si hay varias versiones, pedir al usuario cuál está vigente. No basta con la mayor
     (ver Doc 16).
   - Detectar si el mismo horario ya existe en la base de datos (misma nómina, periodo,
     versión y fecha).
8. **Guardar el PDF original** y relacionarlo con el horario importado, como evidencia.
9. Dejar la interfaz de "lector" común para que Excel y CSV entren después por el mismo
   proceso de vista previa.

## 9. Limitaciones

- El catálogo "verificado" se armó con las aulas y actividades de estos mismos 26 PDF.
  En un semestre nuevo pueden aparecer aulas o materias que no estén en el catálogo:
  esas celdas se marcarán para revisión (no se corregirán solas).
- La transcripción de referencia se hizo revisando las imágenes. Se validó con los
  totales del QR, pero conviene que una persona de la Jefatura revise al azar 2 o 3
  documentos.
- Solo se probó con documentos de un periodo y una plantilla. Si la plantilla cambia,
  habrá que repetir esta evaluación.

## 10. Cómo reproducir

Requisitos: Tesseract con idiomas `eng` y `spa` (`brew install tesseract tesseract-lang`).

```bash
# Copiar y descomprimir el ZIP en una carpeta FUERA del repositorio, por ejemplo /tmp/horarios
uv run python herramientas/ocr_prueba/extraer.py /tmp/horarios /tmp/resultado.json
uv run python herramientas/ocr_prueba/evaluar.py /tmp/resultado.json /tmp/verdad --anonimo
```

El formato de la carpeta de transcripción está descrito al inicio de
[evaluar.py](../herramientas/ocr_prueba/evaluar.py).

## Etapa 3: prueba controlada del importador

> Fecha: 2026-11-04. Mismos 26 PDF reales, procesados con el importador completo (API +
> OCR + comparación con catálogos). Por autorización de la Jefatura, los datos reales se
> cargaron **solo en una base de datos aislada** (`asi_archivo_ocr`), con su propio
> usuario y contraseña guardados fuera del repositorio. El usuario de la base de
> desarrollo no tiene acceso a ella. Las cifras de esta sección son anónimas.

### Ronda A: catálogos vacíos (primera importación sin datos previos)

| Resultado | Valor |
|---|---|
| PDF procesados | 26 de 26 (36 páginas), en 12 s |
| Copias detectadas automáticamente | 6 páginas (Doc 01, 03 ×2, 17, 21, 24) |
| Páginas por revisar | 30 (917 celdas) |
| Asignaciones automáticas | 0: sin catálogo no se asigna nada |
| Asignaciones incorrectas | 0 |

Se detectó que la letra de grupo "O" llegaba como el dígito "0" en 6 celdas. Se
corrigió: los grupos son letras, así que los dígitos parecidos (0, 8, 1, 5) se
convierten a O, B, I, S.

### Ronda B: catálogos cargados (simula catálogos ya capturados)

Se cargaron las aulas, asignaturas y docentes de la transcripción verificada.

| Campo | Coincide (automático) | Sugerido (requiere aceptar) | Sin coincidencia (elegir) |
|---|---|---|---|
| Docente | 30 / 30 | 0 | 0 |
| Asignatura | 842 (91.8%) | 40 (4.4%) | 35 (3.8%) |
| Aula | 798 (87.0%) | 113 (12.3%) | 5 (0.5%) |
| Grupo | — | — | 776 letras pendientes de validar · 141 actividades sin grupo |

**Asignaciones automáticas incorrectas: 0. Sugerencias incorrectas: 0.**

### Ronda C: revisión mínima y aprobación

Se aceptaron todas las sugerencias y se aprobaron las páginas que quedaron completas.

| Resultado | Valor |
|---|---|
| Páginas aprobadas directamente | 17 de 30 |
| Páginas con datos por elegir | 13 (35 asignaturas y 5 aulas en total) |
| Celdas de los borradores comparadas con la transcripción | 510 |
| Asignatura, aula y letra de grupo correctas | **510 / 510 (100%)** |
| Celdas faltantes o sobrantes | 0 |

Los 40 datos por elegir son casos que el OCR leyó con errores no corregibles con
seguridad (por ejemplo, el numeral romano final perdido, "Avan I" leído como "Avan"),
o aulas leídas con caracteres de más ("1.4.0" por "L4.0"). El sistema no los adivina:
los muestra en rojo con la imagen del documento para que el usuario elija.

### Qué falta para usar datos reales en la base principal

- Autorización para cargar datos reales fuera de la base aislada.
- Capturar el catálogo real de grupos (carrera, semestre y letra por periodo) para
  validar las 776 letras pendientes.
- Revisar y confirmar con la Jefatura el catálogo de aulas y asignaturas.
