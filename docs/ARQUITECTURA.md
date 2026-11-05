# ASI-ARCHIVO — Arquitectura

Sistema de Asistencia y Archivo Digital de la Jefatura de Electromecánica,
Tecnológico Superior de Jalisco, campus Zapopan.

> Documento vivo: se actualiza al cerrar cada etapa. Última actualización: Etapa 5 y ampliación de Etapa 4 (asistencia por hora).

## 1. Objetivo

Centralizar los horarios docentes, la bitácora diaria de asistencia y el archivo
de documentos de la Jefatura. Debe poder consultarse desde dos computadoras Windows
de la universidad y desde una MacBook, con la misma información en las tres.

## 2. Principios de diseño

1. **Nunca suponer asistencia.** Un docente sin registro del día está *pendiente*.
   El estado "pendiente" no se guarda: es la ausencia de un registro.
2. **El historial no se rompe.** Los horarios se versionan con fechas de vigencia
   en lugar de sobrescribirse. Una falta de septiembre sigue mostrando el horario
   que estaba vigente en septiembre.
3. **No se borra nada.** Los registros se desactivan (*soft delete*) y cada cambio
   queda en la tabla `auditoria`. La base de datos impide modificar o borrar la auditoría.
4. **Ubicación programada ≠ presencia confirmada.** El buscador muestra la ubicación *programada* de un docente según su horario y los avisos registrados. Eso es distinto de que su presencia
   esté registrada.
5. **Sin secretos en el código.** Las credenciales viven en `.env` (fuera de Git)
   o en el llavero del sistema operativo.
6. **Los datos reales no salen sin autorización.** El OCR corre en el servidor propio
   (Tesseract), no en servicios en la nube.

## 3. Arquitectura general

```
 [PC Windows asistente] ─┐
 [PC Windows jefe]   ────┼── HTTPS + token ──► [API FastAPI] ──► [PostgreSQL]
 [MacBook]           ────┘                          │
     (PySide6)                                      ├──► [Almacén de archivos]
                                                    └──► [OCR / Reportes]
```

- **Cliente (PySide6):** solo muestra la información y la envía a la API. No contiene
  reglas de negocio ni credenciales de la base de datos.
- **API (FastAPI):** concentra la lógica, valida los datos, verifica permisos y
  escribe la auditoría.
- **PostgreSQL:** la única fuente de verdad.
- **OCR y reportes:** se procesan en el servidor, así que el resultado es igual en
  Windows y en Mac, y Tesseract no se instala en cada PC.

### Tecnologías

| Área | Tecnología | Motivo |
|---|---|---|
| Lenguaje | Python 3.12 | Un solo lenguaje en cliente y servidor |
| Interfaz | PySide6 (Qt 6) | Escritorio nativo en Windows y macOS; licencia LGPL |
| API | FastAPI + Pydantic | Validación automática y documentación en `/docs` |
| Base de datos | PostgreSQL 17 | Robusta, con búsqueda de texto en español, JSONB, `pg_trgm` y `unaccent` |
| ORM / migraciones | SQLAlchemy 2 + Alembic | Cambios de esquema controlados y reversibles |
| Contraseñas | Argon2 (`argon2-cffi`) | Algoritmo recomendado actualmente para guardar contraseñas |
| Sesión | JWT firmado (`pyjwt`) | Sin estado en el servidor; expira en 8 h |
| Token en el cliente | `keyring` | Llavero de Windows / Llavero de macOS |
| Dependencias | `uv` (espacio de trabajo) | Instalación rápida y reproducible (`uv.lock`) |
| Calidad | `ruff` + `pytest` + GitHub Actions | Estilo uniforme y pruebas en cada *push* |
| OCR (Etapa 3) | PyMuPDF + Tesseract (`eng`) + OpenCV | Los horarios son escaneados; el encabezado se lee del código QR (ver [EVALUACION_OCR.md](EVALUACION_OCR.md)) |
| Reportes (Etapa 7) | Jinja2 + WeasyPrint, `openpyxl` | PDF desde plantillas HTML y Excel nativo |
| Ejecutables (Etapa 8) | PyInstaller | `.exe` para Windows y `.app` para macOS |

## 4. Estructura del repositorio

```
ASI-ARCHIVO/
├── pyproject.toml          # espacio de trabajo uv, ruff y pytest
├── uv.lock                 # versiones exactas de dependencias
├── .env.example            # plantilla de configuración (sin secretos)
├── conftest.py             # las pruebas de interfaz se dibujan sin abrir ventanas
├── shared/asi_shared/      # constantes comunes: estados, días, permisos
├── server/
│   ├── alembic.ini
│   ├── migrations/         # migraciones de la base de datos
│   ├── app/
│   │   ├── main.py         # punto de entrada de la API
│   │   ├── cli.py          # comandos de administración (crear usuarios)
│   │   ├── api/            # endpoints por módulo + dependencias de permisos
│   │   ├── core/           # configuración y seguridad
│   │   ├── db/             # conexión a PostgreSQL
│   │   ├── models/         # tablas (SQLAlchemy)
│   │   ├── importers/      # OCR de horarios y comparación con catálogos
│   │   ├── reports/        # reportes PDF y Excel
│   │   ├── schemas/        # validación de entrada y salida (Pydantic)
│   │   └── services/       # reglas de negocio y auditoría
│   └── tests/
├── client/
│   ├── asi_cliente/
│   │   ├── main.py         # arranque de la app de escritorio
│   │   ├── api/            # cliente HTTP hacia la API
│   │   ├── cuadricula.py   # conversión bloques ⇄ cuadrícula semanal
│   │   ├── views/          # ventanas y pantallas
│   │   └── theme/          # temas claro y oscuro
│   └── tests/
├── herramientas/
│   ├── ocr_prueba/         # evaluación de OCR contra transcripciones (Etapa 1b)
│   └── tests/
├── docs/                   # esta documentación
└── .github/workflows/      # pruebas automáticas
```

Se agregará `deploy/` en la Etapa 8. El código de OCR vive en `server/app/importers/` desde la Etapa 3.

## 5. Modelo de datos

### Implementado en la Etapa 1

| Tabla | Propósito |
|---|---|
| `usuario` | Cuentas del sistema (correo, nombre, hash de contraseña, activo) |
| `rol` | `administrador`, `consulta` |
| `permiso` | Permisos individuales, p. ej. `docentes.editar` |
| `rol_permiso`, `usuario_rol` | Relaciones muchos a muchos |
| `auditoria` | Quién hizo qué, cuándo y desde qué IP; valores antes/después en JSONB. **Solo inserción** (lo garantiza un *trigger*) |

**Roles iniciales:** `administrador` tiene los 14 permisos originales y los agregados por las migraciones. `consulta` solo tiene los
permisos de lectura (`*.ver`). Los permisos se reasignan en la base de datos sin tocar código.

### Implementado en la Etapa 2

| Tabla | Propósito |
|---|---|
| `docente` | Nombre (como en los horarios institucionales), `nombre_normalizado` único (sin acentos, evita duplicados), nómina única, correo, activo |
| `asignatura` | Materias (`tipo = materia`, requieren grupo) y otras actividades (`tipo = actividad`: gestión, tutoría, residencia…). Nombre normalizado único sin signos: "CÁLC. DIF." = "calc dif" |
| `grupo` | Se identifica por **periodo + carrera + semestre + letra** (llave única). Si falta periodo, carrera o semestre queda *pendiente de validación* (Etapa 3) |
| `aula` | Clave única en mayúsculas ("M05", "SALA EM") y descripción |
| `periodo` | Nombre, fechas, estado `borrador / activo / cerrado`. Índice único parcial: **solo un periodo activo**. Las fechas de dos periodos no pueden traslaparse |
| `horario` | Una **versión** del horario de un docente en un periodo: número de versión, estado, origen (`manual / pdf / excel / csv`), fecha y versión del documento institucional, versión base, quién lo creó y quién lo confirmó. Índice único parcial: **una sola versión vigente por docente y periodo** |
| `bloque_horario` | Día (0 = lunes … 5 = sábado), hora de inicio y fin, asignatura, grupo, aula y `grupo_letra` (letra leída del documento cuando aún no se sabe a qué grupo corresponde). Los horarios **por grupo** (Etapa 5) se obtienen de esta misma tabla |

Ningún catálogo se borra: se desactiva. Un registro inactivo sigue apareciendo en los
horarios antiguos, pero no puede usarse en horarios nuevos.

#### Ciclo de vida de un horario

```
                 confirmar (horarios.confirmar)          otra versión confirmada
   borrador ───────────────────────────────▶ vigente ──────────────────────────▶ histórico
      │
      └── descartar ──▶ descartado
```

- Solo los **borradores** se editan. Para cambiar un horario vigente se crea una nueva
  versión (copia de la vigente), se edita y se confirma. La anterior pasa a histórico
  con todos sus bloques: el historial nunca se pierde.
- **Errores** que impiden guardar un borrador: bloques que se traslapan o se repiten,
  hora de fin anterior a la de inicio, materia sin grupo, catálogo inexistente o inactivo.
- **Advertencias** que piden aceptación explícita al confirmar: el aula ya la ocupa otro
  docente a esa hora (en sus horarios vigentes del mismo periodo), o la versión es
  idéntica a la vigente (probable duplicado).
- Un periodo **cerrado** deja todos sus horarios en solo lectura. Un docente **inactivo**
  no recibe versiones nuevas.
- Cada operación queda en `auditoria` con los valores antes y después (los bloques
  completos, en el caso de las ediciones).

#### Endpoints

| Recurso | Rutas | Permiso para leer / modificar |
|---|---|---|
| Docentes | `GET/POST /docentes`, `GET/PATCH /docentes/{id}`, `POST /docentes/{id}/activar\|desactivar` | `docentes.ver` / `docentes.editar` |
| Asignaturas, grupos, aulas | Igual que docentes, en `/asignaturas`, `/grupos`, `/aulas` | `horarios.ver` / `horarios.editar` |
| Periodos | `GET/POST /periodos`, `GET /periodos/activo`, `PUT /periodos/{id}`, `POST /periodos/{id}/activar\|cerrar` | `horarios.ver` / `periodos.gestionar` |
| Horarios | `GET/POST /horarios`, `GET/PATCH /horarios/{id}`, `PUT /horarios/{id}/bloques`, `POST /horarios/{id}/descartar` | `horarios.ver` / `horarios.editar` |
| Confirmar vigente | `POST /horarios/{id}/confirmar` (`aceptar_advertencias`) | `horarios.confirmar` |

Las reglas de negocio responden con `{"detail": mensaje, "problemas": [...]}` y un
código 4xx (404 no existe, 409 conflicto, 422 datos inválidos). La documentación
interactiva completa está en `/docs` con la API en marcha.

### Implementado en la Etapa 3: importación de horarios desde PDF

**Grupos.** Una letra sola no identifica a un grupo (la "A" de 1er semestre no es la
"A" de 7º). El catálogo de grupos guarda periodo, carrera, semestre y letra. Lo que el
PDF trae es solo la letra: se guarda en `bloque_horario.grupo_letra` como **pendiente de
validación**, sin asociarla a ningún grupo. Confirmar un horario con grupos pendientes
genera una advertencia que el administrador debe aceptar.

**Zona de revisión** (nada de esto es un horario oficial):

| Tabla | Propósito |
|---|---|
| `importacion` | Un archivo subido (ZIP o PDF): periodo, quién lo subió, SHA-256, estado `procesando / en_revision / terminada / error / cancelada` y avance |
| `importacion_documento` | Cada PDF: nombre, SHA-256, estado `procesado / duplicado / error` |
| `importacion_pagina` | Una propuesta de horario: encabezado (del QR o del OCR), docente leído y asignado, versión y fecha del documento, horas declaradas, estado `por_revisar / aprobada / descartada / duplicada / error`, horario creado al aprobar |
| `importacion_celda` | Una hora de la cuadrícula: texto OCR (evidencia, no se modifica), recorte de imagen, valores asignados y su estado |

**Comparación con catálogos** (`app/importers/coincidencias.py`). Nunca asigna una
coincidencia dudosa:

| Estado | Cuándo | Qué pasa |
|---|---|---|
| `coincide` | El texto normalizado es idéntico a un único registro | Se asigna |
| `sugerido` | Se parece a un único registro ("MOS" ~ "M05", 1–2 letras distintas con el mismo numeral final) | Se propone; **el usuario debe aceptarlo** |
| `sin_coincidencia` | No se parece a nada, o se parece a varios (ambiguo) | El usuario elige o crea el registro |
| `pendiente` | Grupo: solo se conoce la letra | Se conserva la letra; el grupo se valida después |

**Flujo y reglas** (`app/services/importacion.py`):
1. *Subir.* Solo ZIP o PDF, máximo 60 MB (300 MB descomprimido, 300 PDFs). Del ZIP se
   toma solo el nombre de cada archivo, nunca su ruta. El archivo original no se
   modifica ni se guarda: solo su SHA-256 y el recorte de cada celda.
2. *Duplicados.* Un PDF con la misma huella que otro ya importado (en una importación
   no cancelada) no se procesa. Páginas con el mismo QR dentro de la importación se
   marcan como copias (se pueden restaurar). Al aprobar, si ya existe un horario del
   mismo docente, periodo, versión y fecha del documento, se pide confirmación.
3. *OCR en segundo plano*, en varios procesos. Si un PDF está dañado, solo ese
   documento queda con error.
4. *Revisión.* Se pueden corregir docente, asignaturas, grupos, aulas, días y horas,
   agregar o eliminar celdas. Todo valor que el usuario elige o acepta queda
   `confirmado`. Crear un docente, asignatura o aula nueva es siempre una acción
   explícita del usuario.
5. *Aprobar* solo si no queda nada pendiente; si las horas no coinciden con las del
   documento, se pide confirmación. Aprobar **crea un horario en borrador** (origen
   `pdf`, con versión y fecha del documento). Volverlo vigente sigue siendo el paso de
   confirmación de la Etapa 2 (`horarios.confirmar`).
6. Todo queda en la auditoría: importar, revisar, aceptar sugerencias, aprobar,
   descartar, restaurar y cancelar.

**Formato común de página.** El servicio recibe cada página como encabezado + celdas
(`dia-hora` → actividad, grupo, aula, texto). Un lector de Excel o CSV futuro solo
tendrá que producir ese mismo formato para reutilizar toda la revisión.

**Endpoints** (todos requieren `horarios.editar`):

| Ruta | Uso |
|---|---|
| `POST /importaciones` (multipart: `archivo`, `periodo_id`) | Sube el archivo; responde 202 y el OCR sigue en segundo plano |
| `GET /importaciones`, `GET /importaciones/{id}` | Avance, documentos y páginas con su conteo de pendientes |
| `POST /importaciones/{id}/cancelar` | Descarta lo que quedaba por revisar |
| `GET /importaciones/paginas/{id}` | Detalle: celdas, pendientes y avisos |
| `PUT /importaciones/paginas/{id}` | Guarda la revisión (docente y celdas) |
| `POST /importaciones/paginas/{id}/aceptar-sugerencias` | Acepta todas las sugerencias de la página |
| `POST /importaciones/paginas/{id}/aprobar` | Crea el borrador (`aceptar_diferencia_horas`, `permitir_duplicado`) |
| `POST /importaciones/paginas/{id}/descartar` · `/restaurar` | Descartar o devolver a revisión |
| `GET /importaciones/celdas/{id}/imagen` | Recorte PNG de la celda en el documento original |

**Dónde corre el OCR.** Solo en el servidor (Tesseract con idiomas `eng` y `spa`). Las
computadoras Windows y la Mac solo envían el archivo y muestran la revisión. En un
servidor Windows, si Tesseract no está en el PATH, se indica su ruta con
`ASI_TESSERACT_CMD`. `ASI_OCR_PROCESOS` limita el número de procesos de OCR.

### Implementado en la Etapa 4: bitácora diaria

**Unidad de registro: docente + fecha + turno.** Es una asistencia general (no por
clase), separada por turno: *matutino* si la actividad empieza antes de las 14:00 y
*vespertino* desde las 14:00 (`asi_shared.turno_de`, misma regla en servidor y cliente).

| Tabla | Propósito |
|---|---|
| `asistencia` | Registro real: estado (`asistio / retardo / falto / justificado`), hora real de entrada y salida, observaciones, justificación, copia de lo programado (horario, inicio y fin), si se registró en día inhábil por excepción y número de correcciones. Única por docente, fecha y turno |
| `incidencia` | Nota manual del día (comisión, permiso, salida anticipada, cambio de aula, otra), general o de un docente/turno. Se anula, no se borra |
| `calendario_evento` | Día inhábil, vacaciones o suspensión, de uno o varios días, todo el día o un turno. Tipo `habil` = excepción autorizada que gana sobre los anteriores |
| `horario.vigente_desde / vigente_hasta / vigencia_confirmada` | Intervalo temporal verificado; NULL y false representan vigencia desconocida. Una versión de estado vigente no certifica por sí sola fechas históricas |

**Reglas:**
- La lista del día **se calcula**, no se guarda: docentes con actividades ese día según
  la versión de horario que regía en esa fecha. Sin registro = *pendiente de
  verificar*; en día inhábil = *día inhábil*. **El sistema nunca genera faltas.**
- Domingo y fechas fuera de un periodo no tienen lista.
- Registrar: no se duplica (docente, fecha, turno); solo si el docente tenía actividades
  en ese turno; nada a futuro salvo justificaciones; en día inhábil solo con
  excepción autorizada (`asistencia.corregir`). Validaciones: una falta no lleva horas,
  un retardo lleva hora de entrada, un justificado lleva justificación.
- Corregir: siempre con motivo; corregir días anteriores requiere `asistencia.corregir`.
  El historial (auditoría con antes, después, usuario y motivo) se consulta por registro.
- Periodo cerrado: la bitácora queda de solo lectura.
- Un retardo se sugiere (no se impone) cuando la entrada rebasa la tolerancia configurada; inicialmente 10 min. Solo un administrador puede cambiarla, con auditoría.

**Reportes** (`app/reports/bitacora.py`): bitácora del día y reporte por rango (máx. 93
días, por docente y turno) en **PDF** (carta horizontal, con encabezado institucional,
resumen, incidencias, espacio para firmas «Elaboró / Vo. Bo.» y pie con fecha de
generación) y **Excel** (hoja con filtros y hoja de resumen). Distinguen lo registrado de
lo *pendiente de verificar*. Se generan con reportlab y openpyxl (Python puro: igual en
Windows). El texto del encabezado se configura con `ASI_INSTITUCION` y `ASI_DEPENDENCIA`.

**Endpoints:**

| Ruta | Permiso |
|---|---|
| `GET /bitacora?fecha&turno&docente_id&estado` | `asistencia.ver` |
| `GET /bitacora/exportar?fecha&formato=pdf\|xlsx` · `GET /bitacora/reporte?desde&hasta&docente_id&turno&formato` | `reportes.generar` |
| `POST /asistencias` · `PATCH /asistencias/{id}` (con `motivo`) | `asistencia.registrar` (+ `asistencia.corregir` para días anteriores o días inhábiles) |
| `GET /asistencias/{id}/historial` | `asistencia.ver` |
| `GET/POST /incidencias`, `PATCH /incidencias/{id}`, `POST /incidencias/{id}/anular` | ver: `asistencia.ver`; cambios: `asistencia.registrar` |
| `GET/POST /calendario`, `PUT /calendario/{id}`, `POST /calendario/{id}/anular` | ver: `asistencia.ver`; cambios: `periodos.gestionar` |

La fecha de "hoy" se toma en la zona horaria de la Jefatura (`ASI_ZONA_HORARIA`,
America/Mexico_City), no en la del servidor. En Windows se usa el paquete `tzdata`.

### Planeado

**Asistencia por hora (implementada como ampliación de Etapa 4)**
- `asistencia_hora`: por docente, fecha y tramo programado de hasta 60 minutos, con
  referencia a bloque/versión y copia inmutable de su programación. Estado parcial,
  minutos cumplidos/justificados y reportes con pendientes y suspensiones separados.
- Convive con `asistencia` (legado por turno) sin convertir sus registros automáticamente.
- Migración aditiva `a4h001`; preserva vigencias y auditoría existentes.
- Detalles y pruebas en [ASISTENCIA_POR_HORA.md](ASISTENCIA_POR_HORA.md).

**Documentos (Etapa 6)**
- `categoria_documento`.
- `documento`: título, categoría, fecha, palabras clave y `tsvector` para búsqueda en
  español.
- `documento_version`: ruta en el almacén, SHA-256, tamaño, tipo MIME y quién lo subió.
- `documento_docente`: relación muchos a muchos.

## 6. Seguridad

- **Toda comunicación pasa por la API.** El cliente rechaza URLs `http://` que no
  sean de la propia computadora: en producción solo se acepta HTTPS.
- Contraseñas con Argon2. El sistema exige al menos 10 caracteres.
- El inicio de sesión fallido devuelve el mismo mensaje para un correo inexistente y
  para una contraseña incorrecta, para no revelar qué cuentas existen. Cada intento,
  correcto o fallido, se audita.
- Los tokens expiran en 8 horas. Un usuario desactivado pierde el acceso de inmediato,
  aunque tenga un token vigente.
- Los permisos se verifican en el servidor con `requiere_permiso(...)`. El cliente
  solo oculta las secciones no permitidas; eso es una comodidad, no la protección real.
- **Pendiente para la Etapa 8:**
  - Tokens de renovación revocables.
  - Límite de intentos de inicio de sesión.
  - Respaldos cifrados automáticos.
  - Revisión de seguridad.

## 7. Conexión entre equipos y alojamiento

- **Desarrollo (actual):** PostgreSQL y la API corren en la Mac (`localhost`).
- **Producción (por decidir, requiere autorización institucional):** un servidor con
  Docker Compose (PostgreSQL + API + Caddy para HTTPS automático). El acceso remoto
  sería preferentemente por una VPN tipo Tailscale, para no exponer el servicio
  públicamente.
- **Respaldos:** `pg_dump` diario más una copia del almacén de archivos, cifrados y
  guardados fuera del servidor.
- **Antes de cargar datos reales:** autorización por escrito de la Jefatura y revisión
  con TI y la Unidad de Transparencia (legislación de datos personales para sujetos
  obligados, general y de Jalisco). Mientras tanto se desarrolla con datos ficticios.

## 8. Producto mínimo viable

1. Inicio de sesión con roles. ✅ (Etapa 1)
2. Docentes y periodos. ✅ (Etapa 2)
3. Horarios: captura manual ✅ (Etapa 2) e importación asistida del ZIP de PDFs ✅ (Etapa 3).
4. Bitácora diaria con registro de estado, motivo, justificante e historial. ✅ (Etapa 4; el archivo del justificante llega en la Etapa 6)
5. Buscador, semana por grupo y ubicación programada. ✅ (Etapa 5)
6. Servidor desplegado con HTTPS y respaldos.

## 9. Etapas

| Etapa | Contenido | Estado |
|---|---|---|
| 1 | Estructura, entorno, base de datos, autenticación, ventana de login, CI | ✅ Completa |
| 1b | Prueba de OCR con los PDFs reales (solo local) | ✅ Completa ([resultados](EVALUACION_OCR.md)) |
| 2 | Docentes, periodos, catálogos, captura y edición de horarios con versiones | ✅ Completa |
| 3 | Importación ZIP → PDF → OCR → revisión editable → borrador | ✅ Completa ([resultados](EVALUACION_OCR.md#etapa-3-prueba-controlada-del-importador)) |
| 4 | Asistencia por hora, bitácora por turno conservada, calendario, incidencias y reportes | ✅ Ampliada con asistencia horaria independiente |
| 5 | Buscador, horarios por grupo, cruces, ubicación programada, tolerancia configurable | ✅ Implementada; ver validaciones y límites en documentación de integridad |
| 6 | Archivo digital de documentos | |
| 7 | Reportes PDF y Excel | |
| 8 | Servidor, instaladores, respaldos y revisión de seguridad | |

## 10. Decisiones registradas

| Fecha | Decisión | Razón |
|---|---|---|
| 2026-11-04 | Aplicación de escritorio PySide6 (no web) | Solo 3 equipos; todo en Python. La API permite agregar una versión web después |
| 2026-11-04 | PostgreSQL local vía Homebrew en desarrollo | Más ligero que Docker Desktop; Docker se reserva para el servidor |
| 2026-11-04 | SQLAlchemy síncrono | Más simple de entender y suficiente para el volumen de la Jefatura |
| 2026-11-04 | Las pruebas recrean la BD con las migraciones reales | Así también se prueba que las migraciones funcionan |
| 2026-11-04 | Importación con interfaz común de lectores | Se pidió dejar preparada la importación desde Excel y CSV |
| 2026-11-04 | Encabezado del horario desde el código QR | Exacto y gratuito; el OCR del encabezado queda como respaldo |
| 2026-11-04 | OCR por columna, modelo `eng`, sin diccionario | 100% día/hora y grupo, 97% aula, frente a 81% del primer intento |
| 2026-11-04 | Catálogos de aulas y asignaturas para corregir el OCR | Aula 99.4%; solo se corrige con coincidencia única, si no se marca para revisión |
| 2026-11-04 | Horarios inmutables una vez confirmados; cambios = nueva versión | Conserva el historial exacto que la asistencia necesitará en la Etapa 4 |
| 2026-11-04 | Permiso nuevo `horarios.confirmar` | La versión vigente la decide un administrador de forma explícita |
| 2026-11-04 | Choque de aula entre docentes = advertencia, no error | Hay casos reales (aulas compartidas, eventos); el administrador decide |
| 2026-11-04 | Activar un periodo exige cerrar antes el activo | Evita cambiar de semestre por accidente |
| 2026-11-04 | Grupo como catálogo simple (clave) | Los PDF solo muestran una letra; la relación grupo–carrera–semestre se definirá con la Jefatura |
| 2026-11-04 | Cuadrícula de horas exactas en la interfaz | Igual al formato institucional; la API admite horas no exactas y la interfaz lo avisa |
| 2026-11-04 | Grupo = periodo + carrera + semestre + letra; letra sola = pendiente | Pedido por la Jefatura: no suponer que la letra identifica al grupo |
| 2026-11-04 | Solo coincidencias exactas se asignan solas; parecidas = sugerencia | No asignar coincidencias dudosas; en la prueba real hubo 0 asignaciones incorrectas |
| 2026-11-04 | Aprobar una página crea un borrador, no un horario vigente | Dos confirmaciones humanas antes de que un horario importado sea oficial |
| 2026-11-04 | No se guarda el PDF original, solo su SHA-256 y recortes de celdas | Minimiza datos personales almacenados; el archivo digital llegará en la Etapa 6 |
| 2026-11-04 | OCR en el servidor, en segundo plano y en varios procesos | Clientes Windows sin Tesseract; 26 PDF en ~12 s sin bloquear la API |
| 2026-11-04 | Pruebas con PDF ficticios generados por código | Las pruebas no pueden contener datos reales; los reales solo en una base aislada |
| 2026-11-04 | Asistencia por docente + fecha + turno (14:00 divide los turnos) | Pedido de la Jefatura; sigue siendo general (no por clase) y deja lista la asistencia por clase |
| 2026-11-04 | La lista del día se calcula; "pendiente" nunca se guarda | Nunca suponer asistencia ni generar faltas automáticamente |
| 2026-11-04 | Vigencia con fechas en cada versión de horario | La bitácora de días pasados usa el horario que regía entonces |
| 2026-11-04 | Corrección = motivo obligatorio; días anteriores requieren `asistencia.corregir` | Correcciones autorizadas y trazables |
| 2026-11-04 | Reportes con reportlab y openpyxl | Python puro, sin dependencias del sistema: funcionan igual en Windows |


## 11. Etapa 5 e integridad temporal

- Servicios de consulta en `server/app/services/consultas.py`; endpoints en
  `server/app/api/consultas.py`; pantallas PySide6 en `client/asi_cliente/views/consultas.py`.
- `GET /buscador`: categorías separadas, texto sin acentos, filtros de programación
  (carrera, semestre, periodo, día 0–5 y turno), fecha de vigencia y paginación.
  Los catálogos sin filtros incluyen registros sin horario; al filtrar programación,
  los resultados deben estar asociados a bloques de versiones verificadas.
- `GET /consultas/grupos`: filtros carrera, semestre, letra y periodo sobre la identidad
  completa del grupo; excluye grupos pendientes. No completa las letras leídas por OCR.
- `GET /consultas/grupos/{id}/horario?fecha`: lunes a domingo; se calcula cada fecha
  por separado, con las versiones que correspondían a ese día. Señala traslapes de grupo
  entre docentes y suspensiones del calendario. No inventa días inhábiles.
- `GET /consultas/grupos/{id}/exportar?fecha&formato=pdf|xlsx`: mismo servicio de consulta,
  firmas por cargo, sin personas fijas; Excel escribe texto literal, nunca fórmulas de catálogos.
- `GET /consultas/docentes/{id}/ubicacion?fecha&hora`: intervalos semiabiertos
  `[inicio, fin)`, horario local de la Jefatura; devuelve `ubicacion_real=null`.
  Considera incidencias generales y por docente/turno y suspensiones registradas.
  Una incidencia de texto libre exige verificación; no se deduce el aula efectiva.
- `GET /consultas/ahora`: reloj y zona del servidor para inicializar la consulta en
  clientes macOS/Windows sin depender de su zona local.
- `GET/PUT /configuracion/asistencia`: tolerancia administrativa 0–120 min; nueva tabla
  singleton `configuracion_asistencia`. Se aplica en API y sugerencias de la interfaz.
- `POST /horarios/{id}/vigencia`: confirmación/corrección de fechas reales con
  `horarios.confirmar`, motivo y auditoría. Serializa confirmaciones por docente y
  rechaza traslapes temporales. Los históricos requieren fin conocido.

Las consultas de grupo requieren `horarios.ver` y `asistencia.ver`; la ubicación suma
`docentes.ver`. Exportar requiere además `reportes.generar`. El buscador solo entrega
categorías autorizadas y no permite usar filtros de horarios sin permiso de lectura.
La configuración solo puede cambiarla el rol administrador.

La migración `e5a001` es nueva y posterior a `8b4cb2f4fef8`; no se modifica una
migración publicada. Conserva las fechas heredadas en auditoría y representa su falta
de certeza con NULL y `vigencia_confirmada=false`. Las asistencias ya registradas
conservan su copia del programa original. La versión oficial sigue disponible aunque
sus fechas aún no estén verificadas. Los borradores confirmados sin fecha explícita
no reciben automáticamente el inicio del periodo.

La protección de pruebas acepta solo la base y usuario `asi_archivo_pytest`, valida
la URL antes de conectar y la identidad/privilegios del servidor antes de cambiar
el esquema. Se usa en pytest, Alembic y CLI. Véase
[INTEGRIDAD_Y_PRUEBAS.md](INTEGRIDAD_Y_PRUEBAS.md) para preparación y política de actualización.

## 12. Decisiones de continuidad

- Se trabaja sobre `etapa-4-bitacora`, sin merge de los PR anteriores. El nuevo PR
  apunta a esa rama para mostrar únicamente el trabajo de esta entrega.
- No se aplican migraciones a la base principal ni a la aislada con datos reales.
- Los justificantes documentales siguen en Etapa 6; los instaladores de Windows y
  macOS siguen en Etapa 8. La validación gráfica automatizada usa Qt offscreen.
- Las fechas heredadas requieren evidencia humana. No se reconstruyen automáticamente
  a partir del periodo, del nombre del archivo ni de la fecha de creación del registro.


## 13. Ampliación de Etapa 4: asistencia por hora

La unidad anterior `docente + fecha + turno` continúa disponible como legado. La
captura principal y los reportes nuevos usan `asistencia_hora`; una hora puede
registrarse como asistida y otra como falta el mismo día. Los parciales representan
un intervalo de presencia dentro del tramo, con minutos justificados explícitos.
La tolerancia no acredita minutos que no se cumplieron.

Se calcula cada fecha con la vigencia confirmada que corresponda. Las capturas llevan
copia del programa; si una corrección de vigencia las deja fuera del programa actual,
se conservan en historial separado y se impide capturar horas nuevas superpuestas.
Los totales actuales no suman esas capturas ni los registros legados por turno.

La nueva migración `a4h001` es solo aditiva y no cambia datos existentes ni migraciones
publicadas. Se conserva la protección de pruebas de Etapa 5. La API, Qt y reportes se
describen en [ASISTENCIA_POR_HORA.md](ASISTENCIA_POR_HORA.md). La Etapa 6 sigue pendiente.
