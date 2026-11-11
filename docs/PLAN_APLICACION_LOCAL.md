# Plan técnico: ASI-ARCHIVO como aplicación local para una sola computadora Windows

> **Estado: plan aprobado; etapa 2 (compatibilidad con SQLite) autorizada.** No se ha
> migrado nada, no se ha borrado ninguna base y la versión que funciona (`entrega-v1`,
> servidor con PostgreSQL) no cambia. Decisiones registradas en la sección 10.
> El rediseño de asistencia sigue en su rama (`asistencia-rediseno`), sin merge.

## 1. Resultado que se busca

Instalar con un `.exe`, abrir desde el escritorio y trabajar. Sin internet, sin Python,
sin PostgreSQL y sin iniciar servicios. Todas las funciones actuales se conservan:
asistencia por hora, docentes, horarios e importación con OCR, justificantes y archivo
digital, reportes PDF/Excel, usuarios, permisos y auditoría. Los datos sobreviven al
cerrar, actualizar o reinstalar, y hay respaldos automáticos con restauración sencilla.

## 2. Cómo está hoy

| Pieza | Hoy | Problema para la versión local |
|---|---|---|
| Interfaz | PySide6 (escritorio) | Ninguno: se conserva |
| Reglas del negocio | FastAPI + servicios (≈8 500 líneas), probadas | Necesita un servidor encendido |
| Base de datos | PostgreSQL 17, 8 migraciones Alembic | Hay que instalar y mantener PostgreSQL |
| Archivo digital | Carpeta privada, archivos con nombre UUID y huella SHA-256 | Pide antivirus ClamAV |
| OCR de horarios | Tesseract en el servidor | Hay que incluirlo en el instalador |
| Respaldos | restic cifrado, dentro de Docker | Depende de Docker |
| Instalador Windows | PyInstaller + Inno Setup (solo la aplicación de escritorio) | No incluye el servidor |

Puntos de la base que dependen de PostgreSQL y hay que adaptar:

- **Protecciones que impiden alterar la historia:** la auditoría no se puede modificar ni
  borrar, los documentos y sus versiones no se pueden eliminar y los vínculos de los
  justificantes tampoco. Hoy son *triggers* de PostgreSQL; SQLite también tiene triggers,
  con otra sintaxis.
- **Columnas `JSONB`** (auditoría y encabezado del OCR) → tipo `JSON`, compatible con ambas bases.
- **4 reglas de duración** con `EXTRACT(EPOCH …)` → se reescriben con funciones de SQLite y
  se verifican también en el programa.
- **5 bloqueos de fila** (`SELECT … FOR UPDATE`) contra registros simultáneos → en SQLite
  hay un solo escritor a la vez y las transacciones se abren en modo exclusivo
  (`BEGIN IMMEDIATE`), lo que da la misma garantía.
- **Fechas con zona horaria:** SQLite no las guarda de forma nativa → un tipo propio que
  guarda en UTC y devuelve la hora con zona, para que las comparaciones no cambien.
- **Índices únicos parciales:** SQLite los admite.
- **Roles de base con permisos mínimos:** no existen en SQLite. Se compensan con los
  triggers y con permisos de Windows sobre la carpeta de datos (ver riesgos).

## 3. Arquitectura propuesta

**Una sola aplicación, con el «servidor» por dentro.** La aplicación de escritorio carga
las mismas reglas de FastAPI *dentro del mismo programa* y les habla directamente, sin red
ni puerto abierto. Así funcionan hoy las pruebas automáticas. Ventajas:

- No se reescribe la lógica de asistencia, permisos ni auditoría: es el mismo código, ya probado.
- No hay servicio que iniciar ni puerto que el antivirus o el firewall puedan bloquear.
- La versión con servidor (PostgreSQL) sigue existiendo mientras se valida la local.

```
ASI-ARCHIVO.exe
 ├─ Interfaz PySide6 (pantallas actuales)
 ├─ Reglas FastAPI dentro del mismo programa (sin red)
 ├─ SQLite  → %LOCALAPPDATA%\ASI-ARCHIVO\datos\asi-archivo.db
 ├─ Archivo → %LOCALAPPDATA%\ASI-ARCHIVO\archivo\        (PDF e imágenes)
 ├─ Respaldos → %LOCALAPPDATA%\ASI-ARCHIVO\respaldos\    (+ copia externa)
 ├─ Tesseract incluido (OCR sin internet)
 └─ Antivirus: Microsoft Defender de Windows
```

Cambios necesarios, sin tocar las reglas del negocio:

1. **Base compatible con SQLite y PostgreSQL a la vez** durante la transición: tipos `JSON`,
   fechas en UTC, triggers en la sintaxis de cada base y migración inicial propia para SQLite.
2. **Modo local de arranque:** sin pantalla de «servidor»; la franja dirá «ESTA COMPUTADORA».
   La primera vez se crea la base y se pide la cuenta de administrador.
3. **El OCR se procesa en segundo plano** (hilo o proceso aparte) para que la ventana no se
   congele mientras lee un ZIP de horarios.
4. **Una sola ventana a la vez** (bloqueo de instancia), para no tener dos escritores sobre
   la misma base.
5. **Clave de sesiones** generada en la primera ejecución y guardada protegida por Windows
   (DPAPI, mediante el llavero del sistema).

**Una sola cuenta de administrador (decisión 2).**

- Una cuenta con usuario y contraseña, con acceso a todas las funciones. No hay pantalla
  para crear ni administrar otros usuarios.
- El código de roles y permisos se conserva por dentro: el administrador los tiene todos.
  Así no se reescriben reglas probadas y la auditoría sigue registrando quién hizo cada cambio.
- **Las cuentas que ya existen en los datos trasladados no se borran.** Se conservan
  desactivadas, porque la auditoría histórica las menciona. La historia no se modifica.
- **Cambiar la contraseña:** Administración › Cambiar contraseña. Pide la actual y la nueva,
  y queda en la auditoría.
- **Recuperar la contraseña sin internet:** al configurar la aplicación por primera vez se
  genera un **código de recuperación**. Se muestra una sola vez y se puede imprimir o guardar
  en un **kit de recuperación** (PDF) para tenerlo fuera de la computadora. En la pantalla de
  inicio, «¿Olvidaste tu contraseña?» pide ese código y permite poner una contraseña nueva.
  Después se genera un código nuevo y el anterior deja de servir. En la base solo se guarda la
  huella del código, nunca el código. Los intentos fallidos tienen el mismo límite que el
  inicio de sesión y todo queda en la auditoría.
- **Si se pierden la contraseña y el código, no hay otra forma de entrar** sin acceso técnico
  a la base. Por eso el kit se guarda fuera de la computadora.

## 4. Archivos: PDF, imágenes y justificantes

- **Dónde:** `%LOCALAPPDATA%\ASI-ARCHIVO\archivo\`, fuera de la carpeta del programa (las
  actualizaciones y la desinstalación no la tocan) y fuera de las carpetas que sincroniza
  OneDrive.
- **Cómo:** igual que hoy. Cada versión se guarda con un nombre UUID sin extensión, su
  huella SHA-256 queda en la base y nunca se sobrescribe ni se borra. Las vistas previas se
  generan al momento y no se guardan.
- **Antivirus:** antes de aceptar un archivo se analiza con Microsoft Defender
  (`MpCmdRun.exe`), que viene con Windows 10 y 11 y funciona sin internet con las últimas
  firmas descargadas. Si Defender está apagado o lo sustituye otro antivirus, la carga queda
  bloqueada con un mensaje claro, como hoy.
- **Recortes del OCR:** las imágenes de cada celda importada siguen dentro de la base.

## 5. Respaldos y restauración

**Qué contiene cada respaldo:** una copia consistente de la base (API de respaldo de SQLite,
segura con la aplicación abierta), todos los archivos del archivo digital y un manifiesto
(versión del esquema, registros por tabla y huella de cada archivo). Todo en un solo
archivo `ASI-ARCHIVO-AAAA-MM-DD-HHMM.asiresp`, que es un ZIP con verificación de integridad.

**Cuándo se hacen solos:**
- Una vez al día, al abrir la aplicación por primera vez ese día.
- Al cerrar, si hubo cambios.
- Siempre antes de actualizar la versión, de cualquier cambio de esquema y de restaurar.

**Cuántos se conservan:** los últimos 14 diarios, 8 semanales y 12 mensuales. Los archivos
solo se copian si cambiaron, así que el espacio crece poco.

**Copia fuera de la computadora (muy recomendada):** una carpeta de red o una memoria USB
elegida en Administración › Respaldos. Un respaldo en el mismo disco no protege si el disco
se daña o la computadora se pierde.

**Restaurar (Administración › Respaldos):**
1. Se elige el respaldo y se pulsa **Verificar**: se abre en una copia temporal y se
   comprueban integridad, registros y huellas.
2. Se pulsa **Restaurar**: antes se hace un respaldo del estado actual, se reemplaza la
   base y el archivo de forma atómica y se reinicia la aplicación. Si algo falla, se
   regresa solo al estado anterior.

**Reinstalar o cambiar de computadora:** desinstalar **no borra** los datos ni los respaldos.
Al reinstalar, la aplicación los encuentra sola. En una computadora nueva, la primera
pantalla ofrece **Restaurar desde un respaldo** (archivo `.asiresp`).

**Cifrado (decisión 3):** todos los respaldos se cifran (AES-256) con una **contraseña de
respaldos** que se define al configurar la aplicación. Se incluye en el kit de recuperación
para guardarla fuera de la computadora. **Sin ella los respaldos no se pueden abrir.**
La aplicación crea los respaldos sola, sin pedirla cada vez: la guarda protegida por Windows
(DPAPI) en esa computadora. Para restaurar en una computadora nueva hay que escribirla.

**Copia externa (decisión 4):** respaldos en la computadora y botón **Copiar a USB**, que
también avisa si hace días que no se hace una copia externa.

## 6. Instalación y actualizaciones

- **Instalador `.exe`** (Inno Setup) para Windows 10 (22H2) y 11, de 64 bits. No pide
  permisos de administrador: se instala para el usuario en
  `%LOCALAPPDATA%\Programs\ASI-ARCHIVO`, con acceso directo en el escritorio.
- **Incluye todo:** Python, PySide6, las reglas FastAPI, SQLite, Tesseract con español e
  inglés, y la generación de PDF y Excel. Tamaño estimado: 250–350 MB instalado.
- **Actualizar** = ejecutar el instalador nuevo. Solo se reemplaza el programa. Al abrir:
  respaldo automático → actualización del esquema → verificación; si algo falla, se
  restaura el respaldo y se avisa.
- **Firma digital:** sin certificado de firma de código, Windows SmartScreen mostrará
  «Editor desconocido» la primera vez (se continúa con «Más información › Ejecutar de
  todas formas»). Para quitar el aviso hace falta un certificado institucional.

## 7. Migración de los datos actuales sin perder información

**Qué datos pasan (decisión 1):** los **26 PDF reales** y toda la información verdadera de
docentes y horarios. **No** se trasladan asistencias ni registros de prueba.

**Antes de trasladar, un inventario para separar lo real de lo de prueba** (solo lectura):
- Por tabla y por registro: quién lo creó, cuándo y desde dónde (auditoría). Por ejemplo, las
  cuentas `@prueba.local`, las altas hechas por pruebas automáticas y las capturas hechas
  durante las revisiones.
- Docentes: los que aparecen en los PDF importados contra los creados a mano para probar
  (por ejemplo, «DOCENTE PRUEBA …»).
- Asistencias, horarios en borrador y catálogos creados en las demostraciones.
- El inventario se entrega como reporte para que **tú confirmes registro por registro**
  qué es real antes de trasladar nada.

Herramienta de traslado `exportar-a-local` (se ejecuta una vez):

1. Abre la base PostgreSQL de origen en **solo lectura**. Nunca la modifica.
2. Crea un archivo SQLite **nuevo** con el esquema local.
3. Copia todas las tablas **conservando los mismos identificadores**, fechas, auditoría,
   versiones de documentos, vínculos y recortes del OCR.
4. Copia los archivos del archivo digital y comprueba la huella SHA-256 de cada uno.
5. **Verificación:**
   - Registros por tabla.
   - Suma de comprobación por tabla.
   - Totales de horas por día iguales en ambas bases.
   - Reportes PDF y Excel equivalentes.
   - Huellas de todos los archivos.
6. Genera un informe. Si algo no coincide, el archivo nuevo se descarta y el origen sigue
   intacto.

**Ensayos:** primero con la base de pruebas y la de revisión (datos ficticios); después,
con autorización, con una **copia** de la base real. PostgreSQL, FastAPI con servidor y sus
bases **no se eliminan** hasta que la versión local pase la aceptación.

## 8. Etapas

| # | Etapa | Entregable | Cómo se comprueba |
|---|---|---|---|
| 1 | Decisiones (sección 10) | Respuestas por escrito | Registradas |
| 2 | Base compatible con SQLite y PostgreSQL | Tipos, triggers, reglas y migración inicial SQLite | La suite completa pasa **en ambas** bases |
| 3 | Modo local integrado, cuenta única y recuperación | La aplicación arranca sola con SQLite, primera ejecución, OCR en segundo plano, instancia única | Pruebas de arranque, OCR sin congelar la ventana y cierre y reapertura sin pérdida |
| 4 | Archivo digital local | Carpeta local y Defender | Carga, versiones, inmutabilidad, archivo de prueba EICAR rechazado |
| 5 | Respaldos cifrados y restauración | Respaldos automáticos, verificación, restauración y copia externa | Restaurar en limpio y comparar; corte de energía simulado |
| 6 | Inventario real/prueba y traslado de datos | Herramienta `exportar-a-local` e informe | Ensayos con bases ficticias y luego con una copia autorizada |
| 7 | Instalador | `.exe` con todo incluido; actualización y desinstalación sin perder datos | Windows 10 y 11 limpios: instalar, usar, actualizar, desinstalar, reinstalar y encontrar los datos |
| 8 | Aceptación | Uso real supervisado en la computadora de la Jefatura | Lista de aceptación firmada; solo entonces se decide retirar el servidor |

Cada etapa en su rama y PR, **sin merge** hasta tu autorización.

## 9. Riesgos y cómo se controlan

| Riesgo | Control |
|---|---|
| Diferencias de comportamiento entre SQLite y PostgreSQL (fechas, horas, reglas) | Suite completa en ambas bases durante la transición y comparación de reportes |
| Alguien con acceso a la carpeta podría editar el archivo de la base (no hay roles de servidor) | Triggers de inmutabilidad, carpeta solo para el usuario de Windows, BitLocker recomendado, respaldos externos; opcional: cadena de huellas en la auditoría para detectar alteraciones |
| Disco dañado o computadora robada | Copia externa automática y respaldos verificados |
| Contraseña de cifrado de respaldos perdida | Decidir antes; guardarla en sobre cerrado o en el gestor institucional |
| Defender apagado o sustituido por otro antivirus | La carga de documentos se bloquea con un mensaje claro; se puede configurar otro antivirus compatible |
| Tamaño del instalador por OCR y Qt | Excluir módulos de Qt que no se usan; tamaño medido en cada versión |
| Aviso de SmartScreen sin firma | Certificado institucional, o instrucciones de primera instalación |
| Actualización a medias por un corte de energía | Respaldo previo, migración en transacción y reversión automática |
| Dos ventanas abiertas sobre la misma base | Bloqueo de instancia única |
| OneDrive o carpetas sincronizadas corrompen la base | Datos en `%LOCALAPPDATA%` (no se sincroniza); aviso si se elige una carpeta sincronizada para la copia externa |
| Datos reales en entornos de prueba | Ensayos solo con bases ficticias o copias autorizadas, como hasta ahora |

## 10. Decisiones registradas

1. **Datos:** conservar los 26 PDF reales y la información verdadera de docentes y horarios;
   no trasladar asistencias ficticias. Antes, inventario de lo real y lo de prueba.
2. **Usuarios:** una sola cuenta de administrador, con cambio y recuperación de contraseña
   sin internet. Se conservan la auditoría y el historial completos.
3. **Respaldos:** automáticos, cifrados y restaurables; contraseña de recuperación guardada
   fuera de la computadora (kit de recuperación).
4. **Copia externa:** en la computadora y opción de copiar a una memoria USB.
5. **Antivirus:** Microsoft Defender cuando esté disponible.
6. **Instalador:** sin certificado por ahora. Windows SmartScreen mostrará «Windows protegió
   su PC · Editor desconocido» la primera vez; se continúa con **Más información › Ejecutar
   de todas formas**. Algunos antivirus pueden revisar el instalador unos segundos. El manual
   lo explicará con imágenes.
7. **Computadora:** antes del instalador definitivo se verificarán versión de Windows,
   arquitectura de 64 bits, espacio libre, si Defender está activo y si hay puerto USB.

## 11. Pruebas para autorizar la implementación

- Suite completa (389 pruebas con el rediseño de asistencia) en **SQLite y PostgreSQL**, con los mismos resultados.
- Comparación de totales de asistencia por hora y de reportes PDF y Excel entre ambas bases
  con los mismos datos ficticios.
- Inmutabilidad: intentar modificar o borrar auditoría, documentos, versiones o vínculos
  directamente en SQLite debe fallar.
- Respaldos: crear, verificar, restaurar en limpio y comparar registro por registro y
  huella por huella; restaurar después de desinstalar y reinstalar.
- Corte simulado durante un respaldo, una actualización y una restauración, sin pérdida.
- Archivo digital: PDF, PNG y JPEG válidos aceptados; archivo de prueba EICAR rechazado
  por Defender; versiones inmutables.
- OCR sin internet (adaptador de red apagado) con horarios ficticios.
- Instalador en Windows 10 y 11 limpios (máquina virtual y GitHub Actions): instalar,
  abrir desde el escritorio, registrar asistencia, cerrar, reabrir, actualizar, desinstalar,
  reinstalar y comprobar que los datos siguen ahí.
- Prueba de uso con la Jefatura en la computadora real, con datos ficticios, antes de
  cargar datos reales.
