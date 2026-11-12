# Etapa 3 · Aplicación local integrada

**Ramas:** `integracion-local` (rediseño de asistencia + SQLite) y `etapa3-aplicacion-local`
(esta etapa, que parte de la integración). Sin merge. `main`, PostgreSQL, FastAPI y las
bases existentes no se modificaron ni se migraron.

## 1. Integración del rediseño de asistencia con SQLite

`asistencia-rediseno` se unió sobre `sqlite-compatibilidad` sin conflictos. El registro
rápido (cuatro botones por fila, cinco tarjetas, filtros y correcciones con motivo) pasó
completo en las dos bases antes de empezar la etapa 3:

| Suite | PostgreSQL | SQLite |
|---|---|---|
| Integración (antes de la etapa 3) | 407 aprobadas | 401 aprobadas, 6 omitidas |

### Las pruebas omitidas en SQLite y sus equivalentes

| Prueba propia de PostgreSQL | ¿Qué protege? | Equivalente en SQLite |
|---|---|---|
| Migración aditiva de asistencia por hora | Que Alembic no altere registros | No aplica: la base local se crea nueva en la versión `e6a001` y nunca se recrea (`test_no_recrea_una_base_que_ya_tiene_datos`, `test_version_de_esquema_igual_a_la_ultima_migracion`). La actualización de esquema local es parte de la etapa 7 |
| Migración desde la etapa 4 | Lo mismo, migraciones antiguas | No aplica, por el mismo motivo |
| Variable `ASI_TEST_DATABASE_URL` incorrecta | Que las pruebas no toquen una base real | `test_barrera_rechaza_sqlite_no_autorizado` y la validación de cada conexión (`PRAGMA database_list`) |
| `connect_args` no cambia el destino | Lo mismo | **Nueva:** `test_connect_args_no_puede_cambiar_el_archivo_sqlite` (la barrera se reforzó para rechazar `uri`, `database` y `factory`) |
| `PGOPTIONS` no redirige | Lo mismo | No existe en SQLite. **Nueva:** `test_archivo_adjunto_no_autorizado_se_detecta` (base adjunta con `ATTACH`) |
| Datos iniciales iguales a las migraciones | Roles, permisos, categorías y tolerancia | Corre en el paso PostgreSQL y compara contra la base SQLite |
| Versiones inmutables (antes solo PostgreSQL) | Archivo digital | **Ahora corre en ambas bases**; antes, en SQLite solo se comprobaba que existían las protecciones, no que bloquearan |

Ninguna protección de datos queda sin comprobar en SQLite: auditoría (no se modifica ni se
borra), archivo digital (no se borra), duración de cada hora, duplicados por docente, fecha
y hora, zona horaria y barrera de pruebas.

## 2. Qué hace la aplicación local

- **Arranca sola:** `uv run asi-archivo --local` (el instalador lo hará con su acceso
  directo). Las reglas de FastAPI corren **dentro del programa** por un transporte en
  memoria: no se inicia ningún servidor, no se abre ningún puerto y no se usa la red.
- **Datos en esta computadora:** `%LOCALAPPDATA%\ASI-ARCHIVO\datos\asi-archivo.db` (SQLite,
  diario WAL y escritura completa) y `…\archivo\` para los documentos. Al cerrar, el diario
  se vuelca a la base. Desinstalar no tocará esa carpeta.
- **Primera ejecución:** se crea la base y se pide la **única cuenta de administrador**.
- **Al volver a abrir:** se verifica la base (versión, tablas, protecciones e integridad).
  Si algo no coincide, la aplicación se detiene con un mensaje **y no modifica nada**.
- **Una sola ventana:** un bloqueo impide abrir dos veces la aplicación sobre la misma base.
- **OCR en segundo plano:** en modo local el OCR corre en un hilo aparte. La importación
  responde de inmediato y la ventana no se congela. Si se cierra a mitad del OCR, al abrir
  se marca esa importación con error y se avisa para volver a importarla.
- **Franja «ESTA COMPUTADORA · datos guardados en este equipo, sin internet»** (verde azulado).
- **Clave de las sesiones:** se crea la primera vez y se guarda en el llavero del sistema
  (en Windows, el Administrador de credenciales, protegido por DPAPI).

## 3. Cuenta única, contraseña y recuperación sin internet

- **Una sola cuenta.** `/local/cuenta` solo funciona si la base no tiene ninguna cuenta. No
  hay pantalla ni ruta para crear otras. La cuenta tiene el rol «administrador», con todos
  los permisos.
- **Cambiar la contraseña:** *Administración › Configuración › Cambiar contraseña*. Pide la
  actual, exige al menos 10 caracteres y una contraseña distinta, cierra las demás sesiones
  y queda en la auditoría. También funciona con el servidor institucional.
- **Código de recuperación:** se genera al crear la cuenta. Son 25 caracteres (125 bits)
  sin letras que se confundan. Se muestra **una sola vez** y la ventana no se cierra hasta
  marcar «Ya guardé el código fuera de esta computadora». Se puede guardar como **kit de
  recuperación en PDF**. En la base solo queda su huella Argon2.
- **«¿Olvidaste tu contraseña?»** en la ventana de inicio: usuario, código y contraseña
  nueva. Al usarse, el código anterior deja de servir y se muestra uno nuevo.
- **Intentos limitados:** después de 10 intentos fallidos en 15 minutos se bloquea, aun
  con el código correcto. Cada intento queda en la auditoría.
- **Nuevo código** (si se pierde el kit): *Configuración › Generar nuevo código*. Pide la
  contraseña.
- **La auditoría nunca se borra.** Las protecciones lo impiden y hay una prueba que lo
  comprueba.

La tabla del código (`cuenta_recuperacion`) existe **solo en la base local**: el esquema de
PostgreSQL y sus migraciones no cambiaron.

## 4. Resultados de las pruebas

| Suite | Resultado |
|---|---|
| PostgreSQL (servidor, como hoy) | **420 aprobadas**, 10 omitidas (propias de la base local) |
| SQLite (aplicación local) | **424 aprobadas**, 6 omitidas (propias de PostgreSQL, ver tabla) |
| Ruff (estilo) | Sin observaciones |

Pruebas nuevas principales:
- **De punta a punta, en dos procesos y con la red bloqueada** (`test_modo_local.py`):
  1. Abre la aplicación y crea la cuenta.
  2. Captura periodo, docente y horario.
  3. Registra «Asistió» y «Falta». Una segunda captura de la misma hora se rechaza (409).
  4. Cierra. Otro proceso la vuelve a abrir, entra y encuentra lo mismo.
  5. Lee directamente el archivo SQLite y comprueba la integridad, una sola cuenta, la
     auditoría y que el diario quedó vacío.
- **Cuenta** (`test_cuenta_local.py`, 13 pruebas): una sola cuenta, datos inválidos,
  cambio de contraseña, recuperación, código renovado, límite de intentos, auditoría
  inmutable y rutas inexistentes en modo servidor.
- **OCR** sin detener la respuesta y la marca de importaciones interrumpidas.
- **Ventanas:** contraseña corta o distinta, código que no se cierra sin confirmar, kit PDF,
  inicio de sesión local y primera ejecución.

## 5. Pendiente para las siguientes etapas (sin empezar)

- **Etapa 4:** antivirus con Microsoft Defender. Hoy, en desarrollo, la carga de documentos
  en modo local funciona sin antivirus. La versión empaquetada **exige** antivirus, así que
  Defender debe quedar listo antes del instalador.
- **Etapa 5:** respaldos cifrados y restauración.
- **Etapa 7:** el instalador, incluido Tesseract, y la actualización de esquema de la base
  local. El transporte en memoria usa `starlette.testclient`, que avisa que a futuro
  necesitará `httpx2`: se fijarán versiones al empaquetar.

## 6. Cómo probarlo en la Mac (datos ficticios)

```
uv run python ~/ASI-ARCHIVO-DATOS/lanzadores/abrir.py local
```

Usa la carpeta de ensayo `~/ASI-ARCHIVO-DATOS/ensayo-local`, separada de la demostración y
del servidor de revisión. La primera vez pide crear la cuenta y muestra el código. Después
se puede registrar asistencia, cerrar y volver a abrir para comprobar que todo sigue ahí.
