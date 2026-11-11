# Etapa 6: archivo digital privado

Rama basada en el PR #7 (`ampliacion-etapa-4-asistencia-hora`, `bac79b5`). Se conserva
la cadena de PR sin fusionarla. Primero se completó la
[revisión funcional de asistencia por hora](ASISTENCIA_POR_HORA.md#revisión-funcional-previa-a-etapa-6).

## Operación

En **Documentos**, carga PDF, PNG o JPEG. Indica nombre, fecha del documento y categoría;
docente y periodo son opcionales para documentos generales. Hay categorías iniciales
de horario original, justificante, permiso, comisión y otro documento. La API permite
crear categorías adicionales con permiso de gestión.

Los filtros buscan nombre y docente sin distinguir acentos, periodo, categoría y rango
de fecha del documento (no fecha de carga). La lista se pagina de 50 en 50 y puede incluir
archivados. Selecciona una versión y página para visualizarla. La vista previa es una
imagen pasiva generada en el servidor; nunca ejecuta JavaScript ni abre enlaces del PDF.
La aplicación no almacena vistas previas en disco. El original solo se guarda en una
ruta elegida por el usuario al descargarlo con permiso.

**Nueva versión** exige motivo y conserva los bytes, hash y autor de todas las anteriores.
La edición de metadatos queda auditada con antes, después y motivo. **Archivar/restaurar**
cambia el estado lógico y conserva originales, vínculos e historial. No existe una
operación de eliminación definitiva, ni siquiera para el administrador.

Desde **Asistencia por hora → Documentos de esta hora**, consulta evidencias vinculadas
a una captura, carga una nueva o busca una existente. Selecciona explícitamente la
versión para vincularla: nuevas versiones no reemplazan evidencias anteriores. Un
documento puede respaldar varias horas mediante vínculos independientes. Solo categorías
habilitadas como justificantes admiten vínculos; docente y periodo deben coincidir cuando
estén definidos. Retirar el vínculo conserva su registro y exige motivo.

Adjuntar evidencia **no justifica automáticamente** una hora ni acredita presencia.
La modificación del estado sigue el flujo de captura/corrección, con sus permisos y
auditoría. Las asistencias anteriores por turno y las vigencias no se convierten ni alteran.

## Permisos y auditoría

| Acción | Permisos de API |
|---|---|
| Buscar, consultar versiones, historial y vista previa | `documentos.ver` |
| Cargar, agregar versión, editar, archivar/restaurar, crear categoría | `documentos.gestionar` |
| Descargar original | `documentos.ver` + `documentos.descargar` |
| Consultar vínculos de asistencia | También `asistencia.ver` |
| Vincular o retirar evidencia | `documentos.gestionar` + `asistencia.registrar`; en días anteriores, `asistencia.corregir` |

Se conservan los roles existentes: consulta puede ver documentos; administrador puede
gestionarlos. El permiso nuevo de descarga se concede inicialmente solo al administrador.
Los permisos son generales para el archivo; no se implementó autorización individual
por docente o categoría. Antes de usar justificantes reales hay que aprobar qué usuarios
pueden consultar todo el archivo, o definir una política más restrictiva.

Cada búsqueda registra filtros e identificadores devueltos. El detalle, historial, vista
por página, descarga, carga, edición y cambios de estado o vínculos registran usuario y
fecha en la auditoría inmutable. **Historial y accesos** muestra eventos del documento;
las búsquedas se conservan en la auditoría general. Una descarga auditada acredita la
entrega por API; no demuestra que el usuario guardó o leyó el archivo. El historial oculta
datos de vínculos a quien carece del permiso de asistencia.

## Almacén y configuración

Los metadatos residen en PostgreSQL. Los originales se guardan únicamente en el servidor,
fuera del repositorio, con claves UUID opacas sin extensiones. No hay ruta pública ni
endpoint estático. Cada lectura verifica tamaño y SHA-256. Las respuestas de vista y
descarga envían `Cache-Control: no-store` y `X-Content-Type-Options: nosniff`.

| Variable | Valor y uso |
|---|---|
| `ASI_ARCHIVO_RAIZ` | Ruta absoluta dedicada, por defecto `~/.local/share/asi-archivo/documentos` |
| `ASI_ARCHIVO_MAX_MB` | 20; admite de 1 a 50 MB por original |
| `ASI_ARCHIVO_ANTIVIRUS_CMD` | Ruta absoluta de un ejecutable local compatible con `clamscan` |
| `ASI_ARCHIVO_REQUERIR_ANTIVIRUS` | `true` por defecto; no puede desactivarse en producción |

Ejemplo conceptual: configura la ruta real del antivirus instalado y una carpeta nueva
dedicada en `.env`, según [.env.example](../.env.example). No utilices carpetas que ya
contengan archivos ni carpetas sincronizadas con servicios de nube. El servidor bloquea
la carga si el antivirus no está configurado, falla, excede 30 segundos o detecta infección.
El antivirus y sus firmas deben instalarse y mantenerse por el responsable del servidor.
Los documentos no se envían a ningún servicio externo de análisis.

En macOS/Linux la carpeta pertenece al usuario del servicio, con permisos `0700` y
archivos nuevos `0600`. En Windows se aplica una DACL NTFS protegida para la identidad
que ejecuta el servidor; si no puede establecerse, se rechaza el almacenamiento. Se
requiere un volumen compatible con esos permisos. El marcador interno vincula la
carpeta a host, puerto y nombre de base mediante hash, sin contraseñas. Una carpeta ya
asociada a otra base es rechazada. No se adopta una carpeta no vacía sin marcador propio.

Usa una carpeta distinta para cada base y cuenta de servicio. En pruebas solo se aceptan
carpetas dentro del directorio temporal del sistema, con marcador explícito creado por
la fixture. La base continúa limitada al rol/base `asi_archivo_pytest`. Una variable
equivocada bloquea la ejecución antes de modificar esquemas o almacenar documentos.

## Validación de archivos y límites

- Se contrasta extensión, MIME declarado y contenido real; se rechazan rutas, controles,
  nombres reservados de Windows y extensiones fuera de PDF/PNG/JPEG.
- Se limita el cuerpo HTTP incluso sin `Content-Length`, y se limita de nuevo la lectura.
- Se rechazan PDF cifrados, reparados, vacíos, con adjuntos, acciones activas, enlaces
  externos o estructuras excesivas. Un PDF institucional con enlace deberá exportarse
  como copia estática antes de cargarlo, sin alterar el original conservado externamente.
- Límites: 150 páginas, 20 000 objetos PDF, hasta 300 imágenes por página; imágenes de
  hasta 25 millones de píxeles y dimensión máxima de 12 000. PNG/JPEG deben ser estáticos.
- El procesador se ejecuta separado, sin configuración ni credenciales de BD/JWT en su
  entorno, con timeout de 15 segundos. En POSIX hay límite de CPU de 8 segundos; en Linux
  también memoria virtual de 768 MiB. La vista se limita a 1280 píxeles de lado máximo.
- El análisis antivirus sucede antes de publicar la versión; después se verifica que no
  cambió el contenido. Un fallo previo a confirmar limpia únicamente el objeto nuevo
  sin publicar. Si falla la confirmación de BD y su resultado es incierto, se conserva
  el objeto privado para reconciliación; nunca se borra un original posiblemente publicado.

Estas barreras y el antivirus reducen riesgos; el subproceso no es un aislamiento completo
del sistema operativo. Deben mantenerse actualizados parsers y firmas. Los bytes de los
originales no se reescriben ni sanitizan silenciosamente; la vista rasterizada es derivada.

## Migración segura y conservación

Nueva revisión **`e6a001`**, padre **`a4h001`**. No cambia ninguna migración publicada.
Agrega cuatro tablas (`categoria_documento`, `documento`, `documento_version` y
`documento_asistencia`), índices, restricciones, categorías iniciales y permiso de
descarga. Triggers bloquean el borrado de documentos, versiones y vínculos y cualquier
UPDATE de versiones. El retiro de vínculos es lógico. El downgrade se bloquea para
evitar pérdida de documentos. No se cambian horarios, vigencias ni capturas existentes.

La migración solo se ha ejecutado en la base exclusiva de pruebas. No se importan datos
reales ni originales de las carpetas de OCR. No se ha migrado ninguna base real.

## Verificación y decisiones para operación real

Las pruebas generan sus propios PDF/imágenes. Cubren API, permisos, descargas, IDOR de
versiones, archivos falsos y activos, límites, antivirus (resultados simulados), integridad,
rutas, protección de datos, inmutabilidad de versiones y vínculos exactos. Qt ejercita
carga, vista, descarga de versiones anteriores, edición, archivo/restauración, vínculos
y formulario modal real. La prueba portable del almacén se ejecuta en macOS y Windows.
La comparación Alembic/modelos y la actualización desde Etapa 4 comprueban integridad.

Resultado local: **263 pruebas aprobadas** (217 conservadas, 2 de verificación funcional
horaria y 44 de archivo digital). Ruff y formato aprobados en 124 archivos Python,
`git diff --check` y `uv lock --check --offline` correctos. `pip-audit` sobre las
dependencias instaladas no encontró vulnerabilidades conocidas; los tres paquetes
propios editables se revisaron como código del repositorio. La revisión de publicación
no incluyó archivos institucionales, originales, claves privadas ni `.env`.

Evidencias locales opcionales en `/private/tmp/asi-revision-funcional`: capturas de
asistencia, lote, PDF y resumen Excel, archivo digital y formulario. No se versionan los
binarios. La revisión visual usa Qt offscreen y PDF renderizado; falta la aceptación del
usuario en sus equipos finales.

Antes de utilizar datos reales se debe acordar:

1. Servidor y cuenta de servicio, ruta privada, capacidad, HTTPS y antivirus operativo con
   firmas actualizadas. La integración real con ese antivirus requiere prueba de despliegue.
2. Usuarios autorizados para justificantes y documentos sensibles; definir si hacen falta
   permisos por categoría o expediente, además de los permisos generales actuales.
3. Política de conservación, acceso a descargas y eventual eliminación excepcional
   autorizada. Esta entrega no ofrece eliminación definitiva.
4. Respaldos privados/cifrados consistentes de **base y almacén**, prueba de restauración,
   recuperación ante fallos y supervisión de espacio. No hay cifrado de originales dentro
   de la aplicación: corresponde proteger disco y respaldos en el despliegue.
5. Revisión y autorización específica para aplicar migraciones sobre una base real.

Ni la apertura del PR ni las pruebas autorizan migraciones en bases reales o merges.
