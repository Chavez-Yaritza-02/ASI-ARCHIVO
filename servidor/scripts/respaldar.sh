#!/bin/bash
# Respaldo completo: base de datos (pg_dump) + documentos + manifiesto de huellas.
# Corre dentro del contenedor "respaldos". Resultado: /respaldos/AAAAMMDD-HHMMSS/
set -euo pipefail
umask 077
marca=$(date +%Y%m%d-%H%M%S)
parcial="/respaldos/.${marca}.parcial"
destino="/respaldos/${marca}"
trap 'rm -rf "$parcial"' ERR
mkdir -p "$parcial"

pg_dump --format=custom --file="$parcial/base.dump"
tar -C /datos -czf "$parcial/documentos.tar.gz" documentos
psql -Atc "SELECT version_num FROM alembic_version" > "$parcial/esquema.txt"
# Conteo de registros por tabla: la verificación lo compara tras restaurar.
psql -At -F ' ' -c "
  SELECT format('SELECT %L, count(*) FROM %I', table_name, table_name)
  FROM information_schema.tables
  WHERE table_schema = 'public' AND table_type = 'BASE TABLE' ORDER BY table_name" \
  | psql -At -F ' ' > "$parcial/conteos.txt"
{
  echo "Respaldo de ASI-ARCHIVO"
  echo "Fecha: $(date '+%Y-%m-%d %H:%M:%S %Z')"
  echo "Esquema: $(cat "$parcial/esquema.txt")"
  echo "Documentos: $(tar -tzf "$parcial/documentos.tar.gz" | grep -c '^documentos/.\+' || true)"
} > "$parcial/LEEME.txt"
(cd "$parcial" && sha256sum base.dump documentos.tar.gz esquema.txt conteos.txt LEEME.txt \
  > MANIFIESTO.sha256)
mv "$parcial" "$destino"
trap - ERR
echo "Respaldo creado: $destino"

# Conservar solo los N más recientes (por defecto 30).
conservar="${ASI_RESPALDOS_CONSERVAR:-30}"
ls -1d /respaldos/2* 2>/dev/null | sort | head -n "-$conservar" | xargs -r rm -rf
