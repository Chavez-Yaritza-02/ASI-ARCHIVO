#!/bin/bash
# Administración explícita. Ninguna operación restaura encima de la base operativa.
set -euo pipefail
cd "$(dirname "$0")"
DC=(docker compose)
confirmar() {
  read -r -p "$1 Escribe $2 para continuar: " respuesta
  [ "$respuesta" = "$2" ] || { echo 'Cancelado.'; exit 2; }
}
verificar() {
  # Cada verificación usa una base aislada NUEVA (en memoria) y la elimina al terminar.
  "${DC[@]}" --profile verificacion rm -sf db-verificacion >/dev/null 2>&1 || true
  "${DC[@]}" --profile verificacion up -d --wait db-verificacion
  # -T y </dev/null: el contenedor no debe consumir la entrada (p. ej. la confirmación).
  if "${DC[@]}" --profile verificacion run --rm -T verificacion "$1" </dev/null; then estado=0; else estado=$?; fi
  "${DC[@]}" --profile verificacion rm -sf db-verificacion >/dev/null 2>&1 || true
  return "$estado"
}
case "${1:-ayuda}" in
  preparar)
    read -r -p 'Dominio oficial del servidor (sin https://): ' dominio
    read -r -p 'TLS: correo del responsable para internet o internal para laboratorio/VPN: ' tls
    python3 preparar.py --dominio "$dominio" --tls "$tls"
    ;;
  instalar)
    [ -f .env ] && [ -d .secretos ] || { echo 'Primero ejecuta ./asi.sh preparar'; exit 2; }
    # Si el proyecto tiene cualquier volumen existente, se rehúsa tratarlo como nuevo.
    proyecto="${ASI_PROYECTO:-asi-archivo}"
    [ -z "$(docker volume ls -q --filter "label=com.docker.compose.project=$proyecto")" ] \
      || { echo 'Existen volúmenes de este proyecto. Instalación nueva bloqueada; no se modifican.'; exit 2; }
    confirmar 'Esto creará infraestructura NUEVA y aplicará migraciones. Requiere autorización de TI.' INSTALAR_NUEVO
    "${DC[@]}" build api respaldos
    "${DC[@]}" up -d --wait db
    "${DC[@]}" --profile mantenimiento run --rm migracion
    "${DC[@]}" exec -T db psql -U asi_admin -d asi_archivo -v ON_ERROR_STOP=1 < db/permisos.sql
    "${DC[@]}" up -d
    echo 'Esquema instalado. Crea usuarios con ./asi.sh usuarios crear-usuario ...'
    ;;
  estado)
    "${DC[@]}" ps
    cat respaldos/ULTIMO_RESULTADO.txt 2>/dev/null || echo 'Aún no existe un respaldo verificado.'
    ;;
  usuarios)
    # entrada.py carga las contraseñas desde los secretos (exec no usa el ENTRYPOINT).
    shift; "${DC[@]}" exec api python /opt/asi/entrada.py python -m app.cli "$@"
    ;;
  respaldar)
    "${DC[@]}" exec -T respaldos /scripts/respaldar.sh
    ;;
  respaldos)
    "${DC[@]}" exec -T respaldos restic snapshots --tag asi-archivo
    ;;
  verificar)
    verificar "${2:-latest}"
    ;;
  restaurar)
    respaldo="${2:?Indica el respaldo: ./asi.sh restaurar <id> (ver ./asi.sh respaldos)}"
    [[ "$respaldo" =~ ^[a-f0-9]{8,64}$ ]] || { echo 'Identificador de respaldo inválido'; exit 2; }
    echo "1/4 Verificando el respaldo ${respaldo} en una base aislada..."
    verificar "$respaldo"
    echo 'ATENCIÓN: se reemplazarán TODOS los datos y documentos actuales por los del respaldo.'
    confirmar 'Antes se creará un respaldo cifrado del estado actual.' RESTAURAR
    echo '2/4 Respaldo de seguridad del estado actual...'
    "${DC[@]}" exec -T respaldos /scripts/respaldar.sh </dev/null
    echo '3/4 Restaurando (la aplicación se detiene unos minutos)...'
    "${DC[@]}" stop api respaldos
    "${DC[@]}" --profile restauracion run --rm -T restauracion "$respaldo" </dev/null
    echo '4/4 Iniciando servicios...'
    "${DC[@]}" up -d --wait api respaldos
    echo 'Restauración terminada. Comprueba con ./asi.sh estado y entrando a la aplicación.'
    ;;
  actualizar)
    echo 'Pasos para actualizar (manual): docs/MANUAL_ADMINISTRADOR.md, sección Actualizar.' >&2
    exit 2
    ;;
  certificado)
    mkdir -p certificado
    [ ! -e certificado/ASI-ARCHIVO-raiz.crt ] || { echo 'Ya existe una copia: no se sobrescribe'; exit 2; }
    "${DC[@]}" cp https:/data/caddy/pki/authorities/local/root.crt certificado/ASI-ARCHIVO-raiz.crt
    echo 'Certificado copiado. Verifica su huella con TI antes de confiar en él.'
    ;;
  registros)
    if [ -n "${2:-}" ]; then "${DC[@]}" logs --tail 100 "$2"; else "${DC[@]}" logs --tail 100; fi
    ;;
  *)
    echo 'Uso: ./asi.sh preparar|instalar|estado|usuarios|respaldar|respaldos|verificar|restaurar|certificado|registros'
    echo 'No se inician migraciones ni restauraciones con estado, verificar o preparar.'
    ;;
esac
