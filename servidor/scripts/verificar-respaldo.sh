#!/bin/bash
# Solo contra el PostgreSQL efímero aislado. No comparte red con la base operativa.
set -euo pipefail
umask 077
[ "${PGHOST:-}" = db-verificacion ] && [ "${PGDATABASE:-}" = asi_archivo_verificacion ] \
  && [ "${PGUSER:-}" = verificador ] || { echo 'Destino de verificación bloqueado'; exit 2; }
export PGPASSWORD="$(cat /run/secrets/db_verificacion)"
respaldo="${1:-latest}"
[[ "$respaldo" = latest || "$respaldo" =~ ^[a-f0-9]{8,64}$ ]] || { echo 'Identificador inseguro'; exit 2; }
trabajo=$(mktemp -d /trabajo/verificacion.XXXXXX)
trap 'rm -rf -- "$trabajo"' EXIT
# Sin lock: repositorio montado en solo lectura y sin retención/borrado automático.
restic --no-lock restore "$respaldo" --tag asi-archivo --target "$trabajo"
mapfile -t encontrados < <(find "$trabajo" -name manifiesto.json -type f)
[ "${#encontrados[@]}" -eq 1 ] || { echo 'Manifiesto ambiguo o inexistente'; exit 2; }
lote="$(dirname "${encontrados[0]}")"
identidad=$(psql -XAt -v ON_ERROR_STOP=1 -c 'SELECT current_database()')
[ "$identidad" = asi_archivo_verificacion ] || { echo 'Base no autorizada'; exit 2; }
# Rechazar bases con tablas, incluso la de verificación: se requiere un contenedor nuevo.
tablas=$(psql -XAt -v ON_ERROR_STOP=1 -c "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")
[ "$tablas" = 0 ] || { echo 'La base de verificación debe estar vacía'; exit 2; }
pg_restore --no-owner --no-acl --exit-on-error --dbname="$PGDATABASE" "$lote/base.dump"
python3 /scripts/verificar-restauracion.py "$lote"
