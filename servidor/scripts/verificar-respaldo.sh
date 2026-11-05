#!/bin/bash
# Verifica un respaldo SIN tocar la base de datos en uso:
#  1. Las huellas del manifiesto coinciden (nada se alteró ni se truncó).
#  2. La base se restaura en una base TEMPORAL y tiene el mismo esquema y los mismos
#     conteos por tabla que al respaldar.
#  3. Cada documento del archivo coincide con la huella SHA-256 registrada en la base.
# Uso (dentro del contenedor "respaldos"): verificar-respaldo.sh [AAAAMMDD-HHMMSS]
set -euo pipefail
respaldo="${1:-$(ls -1d /respaldos/2* 2>/dev/null | sort | tail -n 1 | xargs -r basename)}"
dir="/respaldos/${respaldo}"
[ -n "$respaldo" ] && [ -d "$dir" ] || { echo "No existe el respaldo '${respaldo}'"; exit 2; }
temporal="asi_verificacion_$(date +%s)"
trabajo=$(mktemp -d)
limpiar() { dropdb --if-exists "$temporal" >/dev/null 2>&1 || true; rm -rf "$trabajo"; }
trap limpiar EXIT

echo "Verificando ${dir}"
(cd "$dir" && sha256sum --quiet -c MANIFIESTO.sha256) && echo "  [OK] Huellas del manifiesto"

createdb "$temporal"
pg_restore --no-owner --exit-on-error --dbname="$temporal" "$dir/base.dump"
esquema=$(psql -d "$temporal" -Atc "SELECT version_num FROM alembic_version")
[ "$esquema" = "$(cat "$dir/esquema.txt")" ] || { echo "  [ERROR] Esquema distinto"; exit 1; }
psql -d "$temporal" -At -F ' ' -c "
  SELECT format('SELECT %L, count(*) FROM %I', table_name, table_name)
  FROM information_schema.tables
  WHERE table_schema = 'public' AND table_type = 'BASE TABLE' ORDER BY table_name" \
  | psql -d "$temporal" -At -F ' ' > "$trabajo/conteos.txt"
diff -u "$dir/conteos.txt" "$trabajo/conteos.txt" >/dev/null \
  || { echo "  [ERROR] Los conteos no coinciden"; diff -u "$dir/conteos.txt" "$trabajo/conteos.txt"; exit 1; }
echo "  [OK] Base restaurada en una base temporal: esquema ${esquema}, $(wc -l < "$trabajo/conteos.txt") tablas con los mismos registros"

tar -C "$trabajo" -xzf "$dir/documentos.tar.gz"
psql -d "$temporal" -At -F ' ' -c "SELECT sha256, clave FROM documento_version" > "$trabajo/esperado.txt"
total=$(wc -l < "$trabajo/esperado.txt")
if [ "$total" -gt 0 ]; then
  sed 's#^\([0-9a-f]*\) #\1  documentos/#' "$trabajo/esperado.txt" > "$trabajo/esperado.sha256"
  (cd "$trabajo" && sha256sum --quiet -c esperado.sha256) \
    || { echo "  [ERROR] Algún documento no coincide con su huella"; exit 1; }
fi
echo "  [OK] ${total} documento(s) con su huella SHA-256 correcta"
echo "RESPALDO VÁLIDO: ${respaldo}"
