# Antivirus ClamAV (paquetes oficiales de Debian): servicio clamd + actualización de firmas.
# Funciona en servidores Intel/AMD y ARM. No envía archivos a ningún servicio externo:
# solo descarga firmas de la base pública de ClamAV.
FROM debian:bookworm-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends clamav-daemon clamav-freshclam ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /run/clamav && chown clamav:clamav /run/clamav
COPY clamd.conf /etc/clamav/clamd.conf
COPY iniciar.sh /usr/local/bin/iniciar-antivirus
RUN chmod 755 /usr/local/bin/iniciar-antivirus
EXPOSE 3310
CMD ["/usr/local/bin/iniciar-antivirus"]
