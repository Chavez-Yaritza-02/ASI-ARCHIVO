#!/bin/bash
# Servicio "respaldos": cada día a la hora ASI_HORA_RESPALDO crea y verifica un respaldo.
set -uo pipefail
hora="${ASI_HORA_RESPALDO:-02:30}"
until pg_isready -q; do sleep 5; done
echo "Respaldos programados diariamente a las ${hora} ($(date +%Z))"
while true; do
  objetivo=$(date -d "today ${hora}" +%s)
  ahora=$(date +%s)
  [ "$objetivo" -le "$ahora" ] && objetivo=$(date -d "tomorrow ${hora}" +%s)
  sleep $((objetivo - ahora))
  if /scripts/respaldar.sh && /scripts/verificar-respaldo.sh; then
    date '+%Y-%m-%d %H:%M:%S respaldo correcto' > /respaldos/ULTIMO_RESULTADO.txt
  else
    date '+%Y-%m-%d %H:%M:%S RESPALDO FALLIDO: revisar con docker compose logs respaldos' \
      > /respaldos/ULTIMO_RESULTADO.txt
  fi
done
