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

**El menú de la izquierda tiene seis secciones.** Cada una agrupa sus pantallas en
pestañas en la parte de arriba:

| Sección | Qué encuentras | Atajo |
|---|---|---|
| **Inicio** | Clases de hoy, pendientes, faltas, retardos y accesos rápidos | Ctrl+1 |
| **Asistencias** | Registro por hora · Bitácora del día · Días inhábiles y eventos | Ctrl+2 |
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
- **Horarios › Registro de cambios**: quién creó, editó o confirmó cada horario y cuándo.
- **Administración › Ubicación programada**: dónde *debería* estar un docente a cierta
  hora según su horario (no confirma que esté ahí).

## 5. Registrar la asistencia por hora (uso diario)

**Asistencias › Registro por hora** (o, desde Inicio, **Registrar asistencia**):

1. Elige la **fecha** y pulsa **Consultar horas**. Aparece una fila por cada hora de clase
   o actividad programada ese día.
2. Selecciona una fila y pulsa **Registrar / corregir esta hora** (o doble clic).
3. Elige el estado:

| Estado | Cuándo usarlo |
|---|---|
| **Asistió** | Cumplió la hora completa |
| **Retardo** | Llegó tarde: escribe la hora real de entrada |
| **Parcial** | Estuvo solo una parte: escribe entrada y salida |
| **Falta** | No se presentó |
| **Justificado** | No se presentó con justificación (escribe el motivo) |

4. Pulsa **Guardar**.

**Varias horas a la vez:** selecciona varias filas (Ctrl + clic) y pulsa
**Registrar horas seleccionadas**. Si una falla, no se guarda ninguna; corrige y repite.

**Importante:**
- Una hora sin registrar aparece como **Pendiente**: el sistema **nunca** pone faltas solo.
- En días inhábiles o suspensiones no se esperan registros (**Asistencias › Días inhábiles
  y eventos**).
- **Corregir** un registro pide escribir el **motivo**. Corregir días anteriores solo lo
  puede hacer quien tenga autorización.
- **Historial de esta hora** muestra quién registró o cambió algo, cuándo y por qué.
- **Documentos de esta hora** permite vincular un justificante (ver sección 8). Adjuntar
  un documento **no** cambia el estado: hay que registrar «Justificado».

**Asistencias › Bitácora del día** muestra el registro anterior por turno (matutino /
vespertino) y sus incidencias; se conserva para consulta.

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
   - **Amarillo**: el sistema sugiere un valor; revísalo y acéptalo
     (**Aceptar todas las sugerencias** o doble clic → **Aplicar**).
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
