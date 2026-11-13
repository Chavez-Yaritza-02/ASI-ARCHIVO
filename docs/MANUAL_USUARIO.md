# ASI-ARCHIVO — Manual de uso

Jefatura de Electromecánica · Versión 1.0

ASI-ARCHIVO guarda en un solo lugar los horarios de los docentes, su asistencia por hora,
los documentos de la Jefatura y genera los reportes en PDF y Excel. Toda la información
vive en el servidor central: las dos computadoras de Jefatura ven siempre lo mismo.

---

## 1. Instalar en una computadora con Windows

Pide al administrador el archivo **ASI-ARCHIVO-1.0.0-Windows-x64.exe**.

1. Haz doble clic en el archivo.
2. Si aparece **«Windows protegió su PC»**: pulsa **Más información** → **Ejecutar de todos
   modos**. Aparece porque el programa no tiene firma comercial; es normal.
3. Sigue el asistente (**Siguiente** → **Instalar**). No necesita permisos de administrador.
4. Marca **«Crear un acceso directo en el escritorio»** si lo quieres en el escritorio.

> Si el administrador te lo indica, instala también el **certificado del servidor**
> (sección 9). Sin él, la aplicación dirá que la conexión no es segura.

## 2. Primera vez: conectar con el servidor

La primera vez que abras ASI-ARCHIVO aparece **«Conectar con Jefatura»**:

1. En **Dirección del servidor** escribe la dirección que te dio el administrador
   (empieza con `https://`).
2. Pulsa **1. Comprobar conexión HTTPS**. Debe decir «Conexión HTTPS verificada».
3. Escribe tu **correo** y **contraseña** y pulsa **2. Iniciar sesión y validar permisos**.
4. Pulsa **Abrir ASI-ARCHIVO**.

La dirección queda guardada. Para cambiarla después: botón **Cambiar servidor** en la
ventana de inicio de sesión, o **Inicio → ASI-ARCHIVO → Configurar conexión**.
En **Administración › Configuración** ves el servidor, puedes **Probar conexión** y
cambiar entre tema claro y oscuro.

## 3. Iniciar sesión y moverse por la aplicación

Escribe tu correo y contraseña y pulsa **Entrar**. **«Recordar sesión en este equipo»**
evita escribir la contraseña cada día; no lo marques en computadoras compartidas.

- Después de **10 intentos fallidos** desde una computadora, hay que esperar 15 minutos.
- ¿Olvidaste tu contraseña? Pide al administrador que la restablezca.
- Para salir: **Cerrar sesión** (abajo a la izquierda).

**Franja de arriba: a qué servidor estás conectada.** Siempre se ve, con su dirección:
- Verde, **SERVIDOR INSTITUCIONAL · datos oficiales**: el sistema real de la Jefatura.
- Naranja, **SERVIDOR DE DEMOSTRACIÓN**: para pruebas; no es el sistema oficial.
- Morado, **SERVIDOR DE REVISIÓN · datos ficticios**: solo para revisar la aplicación.
- Gris, **SERVIDOR SIN IDENTIFICAR**: confirma con el administrador antes de capturar.

Lo que guardas queda solo en ese servidor. Si tienes cambios sin guardar (por ejemplo, una
página de importación corregida), al cerrar la ventana o la sesión la aplicación avisa:
**Volver y guardar** o **Salir sin guardar**.

**El menú de la izquierda tiene seis secciones.** Cada una agrupa sus pantallas en
pestañas en la parte de arriba:

| Sección | Qué encuentras | Atajo |
|---|---|---|
| **Inicio** | Clases de hoy, pendientes, faltas, retardos y accesos rápidos | Ctrl+1 |
| **Asistencias** | Registro por hora · Bitácora del día · Días inhábiles y eventos · Importar incidencias (Excel) | Ctrl+2 |
| **Horarios** | Por docente · Por grupo · Importar horarios · Registro de cambios | Ctrl+3 |
| **Docentes** | Catálogo de docentes · Búsqueda general | Ctrl+4 |
| **Reportes** | PDF y Excel de asistencia, bitácora y horarios por grupo | Ctrl+5 |
| **Administración** | Periodos · Catálogos · Documentos · Tolerancia de retardos · Ubicación programada · Configuración | Ctrl+6 |

Arriba siempre ves la **fecha** y el **periodo académico activo**. Cada persona ve solo
lo que su rol permite: el rol **consulta** puede ver, pero no modificar.

En las tablas, el campo **Buscar…** filtra mientras escribes. Los filtros poco usados
están en **Mostrar más filtros** / **Mostrar filtros avanzados**.

## 4. Consultar docentes y horarios

- **Docentes › Catálogo de docentes**: lista y búsqueda (no importan los acentos). Los
  docentes no se borran: se desactivan.
- **Docentes › Búsqueda general**: escribe un nombre para ver su horario y su información.
- **Horarios › Por docente**: elige periodo y docente. Se ven todas las versiones del
  horario; la **vigente** es la oficial. Los semestres anteriores se consultan eligiendo
  su periodo.
- **Horarios › Por grupo**: horario semanal de un grupo.

### Capturar o corregir un horario a mano

En **Horarios › Por docente**, elige periodo y docente. Si el docente no existe, usa
**Nuevo docente…**.

- **Agregar clase…**: día, hora de inicio, hora de fin, materia o actividad, grupo y
  aula. Agrega tantas clases como necesites, también varias el mismo día.
- **Editar clase…** / **Eliminar clase**: elige la clase en la cuadrícula (pestaña
  **Semana**) o en la pestaña **Lista de clases**, que muestra el horario completo.
- Si esa clase ya está, se avisa y no se duplica. Si las horas ya tienen otra clase, se
  pregunta antes de reemplazarla.
- Al **Guardar cambios** se avisa si el aula o el grupo ya están ocupados a esa hora por
  otro docente.
- Si estás viendo la versión vigente, al cambiar algo se crea una **nueva versión
  (borrador)**. La vigente no cambia hasta que confirmes la nueva con **Confirmar como
  vigente**.
- **Semestre nuevo**: elige el periodo nuevo y pulsa **Nueva versión**. Puedes copiar
  las clases del semestre anterior. Los grupos quedan pendientes (solo la letra) para
  asignar los del periodo nuevo.

La asistencia ya registrada conserva el horario que regía ese día. Los horarios
importados por PDF y los capturados a mano son las mismas versiones: no se crean horarios
duplicados.
- **Horarios › Registro de cambios**: quién creó, editó o confirmó cada horario y cuándo.
- **Administración › Ubicación programada**: dónde *debería* estar un docente a cierta
  hora según su horario (no confirma que esté ahí).

## 5. Registrar la asistencia por hora (uso diario)

**Asistencias › Asistencia por hora** (o, desde Inicio, **Registrar asistencia**) se abre en
**Registro rápido**, con las clases del día ordenadas por hora:

- **Arriba:** la fecha, con ◀ ▶ y **Hoy**, y la búsqueda por docente, materia o aula.
- **Filtros siempre visibles:** turno, carrera, grupo, aula, estado y tipo. Para quitarlos, **Limpiar filtros**.
- **Resumen:** horas programadas, horas cumplidas, retardos, faltas y pendientes. Se calculan
  con lo registrado y con los filtros que tengas puestos.
- **Una fila por cada hora:** hora, docente, materia, grupo, aula y estado. Si un docente
  tiene tres horas, aparecen tres filas y cada una se registra por separado.

**Registrar con los botones de cada fila:**

| Botón | Qué pasa |
|---|---|
| 🟢 **Asistió** | Se guarda con un clic |
| 🔴 **Falta** | Se guarda con un clic |
| 🟡 **Retardo** | En la misma fila aparece la **hora real de llegada** (ya viene escrita; cámbiala si hace falta) → **Guardar** o Enter |
| 🔵 **Justificado** | En la misma fila escribe el **motivo** → **Guardar**. Después, el botón **Justificante** permite adjuntar el documento (sección 8) |

- El botón activo se rellena de color y la fila muestra «✓ Guardado» con la hora. Todo se
  guarda en el momento; no hay que pulsar otro botón al final.
- **Observación:** escríbela y pulsa Enter. En una hora pendiente se guarda junto con el registro.
- **Cambiar un estado ya registrado** es una corrección: pulsa el estado correcto, escribe el
  **motivo** y **Guardar**. Queda en el historial con tu nombre. Corregir días anteriores
  solo lo puede hacer quien tenga autorización.
- **Más…** abre la **asistencia parcial** (entrada y salida, minutos justificados), las
  excepciones en días inhábiles y el **historial** de la hora.
- Si escribiste algo y no lo guardaste, la aplicación avisa antes de cambiar de fecha o de cerrar.

**Vista detallada** (pestaña junto a «Registro rápido»): la tabla con todas las columnas, la
captura de **varias horas a la vez** (Ctrl + clic y **Registrar horas seleccionadas**), los
documentos de cada hora y los reportes del día o de un rango de fechas.

**Importante:**
- Una hora sin registrar aparece como **Pendiente**: el sistema **nunca** pone faltas ni
  asistencias solo.
- En días inhábiles o suspensiones no se esperan registros (**Asistencias › Días inhábiles
  y eventos**).
- Adjuntar un documento **no** cambia el estado: hay que registrar «Justificado».

**Asistencias › Bitácora del día** muestra el registro anterior por turno (matutino /
vespertino) y sus incidencias; se conserva para consulta.

### Importar faltas y salidas anticipadas desde Excel

En **Asistencias › Importar incidencias (Excel)**:

1. **Elegir archivo Excel…** (.xlsx). Se reconocen las columnas **FECHA**, **DOCENTE**
   (o PROFESOR / NOMBRE), **INCIDENCIA** (o TIPO), **HORA** y **OBSERVACIONES** (o
   MOTIVO). Leer el archivo **no registra nada**.
2. La tabla muestra cada fila con lo que falta revisar: docente no encontrado, fecha
   incorrecta, posible duplicado, horas ya registradas…
3. **Revisar fila…** (o doble clic):
   - Corrige el docente, la fecha y el tipo: **Falta** o **Salida anticipada**, con su
     hora de salida.
   - Pulsa **Aplicar y ver sus horas**: aparece el horario del docente ese día.
   - **Marca solo las horas que no se cumplieron.** Nada se marca solo. En una salida
     anticipada, **Marcar las horas posteriores a la salida** es una ayuda opcional.
   - Opcional: **Justificada** (con motivo), observaciones y justificante del archivo
     digital.
   - **Guardar revisión.**
4. Marca en la columna **Importar** las filas confirmadas y pulsa **Importar filas
   marcadas**. Se importan todas o ninguna. Las que no marques quedan **pendientes** para
   después. **Descartar fila…** la aparta (con motivo) sin borrarla.

Las horas importadas aparecen en **Registro por hora** y en los reportes, con la
observación «Falta reportada en Excel…» o «Salida anticipada a las HH:MM…». Una hora que
ya tenía registro **no se sobrescribe**: corrígela en Registro por hora. Si cargas el
mismo archivo otra vez, se abre la revisión existente.

## 6. Reportes en PDF y Excel

Sección **Reportes**, en tres pasos:

1. **¿Qué reporte necesitas?** Asistencia por hora de un día, de varios días (hasta 93),
   bitácora del día por turno u horario semanal de un grupo.
2. **Elige las fechas.** En **Mostrar filtros opcionales** puedes limitar por docente,
   turno, tipo de actividad o estado.
3. **Formato** (PDF para imprimir, Excel para revisar) → **Generar reporte…** → elige dónde
   guardarlo. Al terminar, **Abrir el archivo** lo muestra.

Los reportes muestran horas programadas, cumplidas, faltantes, justificadas y pendientes,
y el PDF trae espacio para firmas («Asistente de Jefatura» y «Jefatura de Electromecánica»).
Los botones **PDF del día** / **Excel del día** de Registro por hora siguen disponibles.

## 7. Importar horarios desde PDF (asistente de 4 pasos)

Al inicio de cada semestre, en **Horarios › Importar horarios** (o, desde Inicio,
**Importar horarios**). Abajo están **Anterior** y **Siguiente**:

1. **Periodo.** Elige el periodo al que pertenecen los horarios. Si es un semestre nuevo,
   **Crear periodo nuevo…** (p. ej. ENERO - JUNIO 2027). Cada semestre queda separado y los
   horarios anteriores se conservan.
2. **Archivo.** **Elegir PDF o ZIP…** → **Subir y leer con OCR**. Una barra muestra el
   avance. Si una importación quedó a medias, **Continuar esa importación**.
3. **Revisar.** Elige cada página de la lista y revísala. Colores de la cuadrícula:
   - **Verde**: correcto.
   - **Azul**: lo leído coincide exactamente con una materia, aula o docente dado de alta
     después de importar. Se aceptan todas juntas con **Aceptar coincidencias exactas**.
   - **Amarillo**: el sistema encontró algo **parecido** (una o dos letras distintas o una
     abreviatura). Se confirma **una por una**: doble clic → revisa → **Aplicar**. El
     docente parecido se confirma con **Confirmar docente**.
   - **Rojo**: falta elegir. Doble clic: se ve la imagen del documento original y lo que
     leyó el sistema; elige la materia, grupo o aula correctos, o créalos con **Nueva…**.
   - **Morado**: solo se conoce la letra del grupo (pendiente de validar).

   Revisa el **docente** arriba; si no existe, **Crear docente con el nombre leído**.
   Pulsa **Guardar revisión**.
4. **Confirmar.** La tabla muestra cada página con sus avisos:
   - **Duplicado**: ese documento ya se había importado.
   - **Conflicto**: el aula o el grupo ya están ocupados a esa hora por otro docente.

   Pulsa **1) Aprobar las páginas revisadas**, elige **Aplican desde** (primer día en que
   la asistencia usará estos horarios) y pulsa **2) Confirmar como vigentes**. La versión
   anterior de cada docente pasa al historial; no se borra.

Las páginas repetidas aparecen como **Copia repetida**. **Empezar otra importación**
vuelve al paso 1.

**Cambiar de semestre:** botón **Cambiar periodo** (arriba a la derecha). Cierra el
periodo actual, que queda como historial de solo lectura, y activa el nuevo.

## 8. Documentos

**Administración › Documentos**:

- **Buscar documentos** por nombre o docente; en **Mostrar filtros avanzados**, por
  periodo, categoría o fecha.
- Selecciona un documento, elige **Versión** y **Página** y pulsa **Ver página**.
- **Cargar documento** (PDF, PNG o JPG, máximo 20 MB): nombre, fecha y categoría
  (justificante, permiso, comisión, horario original u otro). El servidor lo revisa con
  antivirus antes de guardarlo.
- **Nueva versión**: reemplaza el archivo conservando las anteriores (pide motivo).
- **Descargar original**: solo usuarios autorizados.
- **Archivar / restaurar**: los documentos nunca se borran.
- **Historial y accesos**: quién consultó o cambió el documento.

## 9. Si algo no funciona

| Mensaje o problema | Qué hacer |
|---|---|
| «No se pudo conectar con el servidor» | Revisa la red. Si sigue, avisa al administrador (puede estar apagado el servidor). |
| «El servidor debe usar HTTPS» | La dirección debe empezar con `https://` |
| Error de certificado o conexión no segura | Falta instalar el certificado del servidor: avisa al administrador |
| «Correo o contraseña incorrectos» | Revisa mayúsculas; el administrador puede restablecerla |
| «Demasiados intentos; espera 15 minutos» | Espera 15 minutos |
| Un docente no aparece en Asistencia por hora | Su horario no tiene fechas de vigencia confirmadas: en **Horarios › Por docente** pulsa **Fechas de vigencia…** |
| «Configura el antivirus…» al cargar documentos | Avisa al administrador |

**Certificado del servidor** (solo si el administrador lo indica): abre el archivo
**ASI-ARCHIVO-raiz.crt** que te entregue → **Instalar certificado** → **Usuario actual** →
**Colocar todos los certificados en el siguiente almacén** → **Examinar** →
**Entidades de certificación raíz de confianza** → **Aceptar** → **Siguiente** →
**Finalizar** → **Sí**. Cierra y vuelve a abrir ASI-ARCHIVO.
