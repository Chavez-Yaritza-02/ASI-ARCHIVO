#!/bin/bash
# Herramienta de administración del servidor de ASI-ARCHIVO.
# Se ejecuta en el servidor, dentro de la carpeta "servidor":  ./asi.sh <comando>
#
#   instalar                  Primera instalación: genera claves, crea la base y el administrador
#   estado                    Muestra si los servicios están funcionando
#   usuarios <subcomando>     Administrar usuarios (ver ./asi.sh usuarios --help)
#   respaldar                 Crea un respaldo ahora (además del automático diario)
#   respaldos                 Lista los respaldos y el resultado del último automático
#   verificar [respaldo]      Comprueba un respaldo restaurándolo en una base temporal
#   restaurar <respaldo>      Reemplaza los datos actuales por los de un respaldo
#   certificado               Copia el certificado raíz (modo ASI_TLS=internal) para las PCs
#   actualizar                Respaldo + nueva versión + migraciones (tras revisar el cambio)
#   registros                 Muestra los últimos mensajes de los servicios
set -euo pipefail
cd "$(dirname "$0")"
DC=(docker compose)

confirmar() {
  read -r -p "$1 Escribe $2 para continuar: " respuesta
  [ "$respuesta" = "$2" ] || { echo "Cancelado."; exit 1; }
}

case "${1:-ayuda}" in
  instalar)
    command -v docker >/dev/null || { echo "Instala Docker Engine primero (ver manual)."; exit 1; }
    if [ -f .env ]; then
      echo "Ya existe servidor/.env: el sistema ya fue instalado. No se modifica."; exit 1
    fi
    read -r -p "Nombre o IP del servidor para las PCs (p. ej. 192.168.10.25): " dominio
    read -r -p "Certificado: 'internal' (red interna) o un correo (dominio público): " tls
    umask 077
    sed -e "s#^ASI_DOMINIO=.*#ASI_DOMINIO=${dominio}#" -e "s#^ASI_TLS=.*#ASI_TLS=${tls:-internal}#" \
        -e "s#^ASI_DB_CONTRASENA=.*#ASI_DB_CONTRASENA=$(openssl rand -hex 24)#" \
        -e "s#^ASI_SECRET_KEY=.*#ASI_SECRET_KEY=$(openssl rand -base64 48 | tr -d '\n/+=')#" \
        .env.ejemplo > .env
    echo "Construyendo e iniciando servicios (la primera vez tarda varios minutos)..."
    "${DC[@]}" up -d --build
    echo "Creando las tablas de la base de datos (instalación nueva)..."
    until "${DC[@]}" exec -T api python -c "import app" 2>/dev/null; do sleep 3; done
    "${DC[@]}" exec -T api alembic upgrade head
    echo; echo "Crea la cuenta del administrador:"
    read -r -p "Correo: " correo; read -r -p "Nombre: " nombre
    "${DC[@]}" exec api python -m app.cli crear-usuario --correo "$correo" --nombre "$nombre" \
      --rol administrador
    echo; echo "Listo. Dirección para las PCs: https://${dominio}"
    [ "${tls:-internal}" = "internal" ] && echo "Ejecuta ./asi.sh certificado y sigue el manual."
    ;;
  estado)
    "${DC[@]}" ps
    echo; cat respaldos/ULTIMO_RESULTADO.txt 2>/dev/null || echo "Aún no hay respaldo automático."
    ;;
  usuarios)
    shift; "${DC[@]}" exec api python -m app.cli "$@"
    ;;
  respaldar)
    "${DC[@]}" exec -T respaldos /scripts/respaldar.sh
    "${DC[@]}" exec -T respaldos /scripts/verificar-respaldo.sh
    ;;
  respaldos)
    ls -1 respaldos | grep -E '^[0-9]{8}-[0-9]{6}$' || echo "No hay respaldos."
    echo; cat respaldos/ULTIMO_RESULTADO.txt 2>/dev/null || true
    ;;
  verificar)
    "${DC[@]}" exec -T respaldos /scripts/verificar-respaldo.sh "${2:-}"
    ;;
  restaurar)
    respaldo="${2:?Indica el respaldo, p. ej. ./asi.sh restaurar 20261104-023000}"
    [ -d "respaldos/$respaldo" ] || { echo "No existe respaldos/$respaldo"; exit 1; }
    echo "ATENCIÓN: se reemplazarán TODOS los datos actuales por los del respaldo $respaldo."
    confirmar "Antes se hará un respaldo de seguridad del estado actual." "RESTAURAR"
    "${DC[@]}" exec -T respaldos /scripts/respaldar.sh
    "${DC[@]}" stop api
    "${DC[@]}" --profile restauracion run --rm restauracion "$respaldo"
    "${DC[@]}" start api
    echo "Restauración terminada. Comprueba con ./asi.sh estado y entrando a la aplicación."
    ;;
  certificado)
    mkdir -p certificado
    "${DC[@]}" cp https:/data/caddy/pki/authorities/local/root.crt certificado/ASI-ARCHIVO-raiz.crt
    echo "Certificado: servidor/certificado/ASI-ARCHIVO-raiz.crt"
    echo "Instálalo en cada PC (ver MANUAL_ADMINISTRADOR, sección Certificado)."
    ;;
  actualizar)
    confirmar "Se hará un respaldo y se aplicarán cambios de versión y de esquema." "ACTUALIZAR"
    "${DC[@]}" exec -T respaldos /scripts/respaldar.sh
    "${DC[@]}" exec -T respaldos /scripts/verificar-respaldo.sh
    "${DC[@]}" up -d --build
    until "${DC[@]}" exec -T api python -c "import app" 2>/dev/null; do sleep 3; done
    "${DC[@]}" exec -T api alembic upgrade head
    echo "Actualización terminada."
    ;;
  registros)
    "${DC[@]}" logs --tail 100 "${2:-}"
    ;;
  *)
    sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'
    ;;
esac
