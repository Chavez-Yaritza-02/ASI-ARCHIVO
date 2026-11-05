-- Ejecutar explícitamente después de migrar; jamás automáticamente desde la API.
\set ON_ERROR_STOP on
REVOKE UPDATE, DELETE ON auditoria FROM asi_app;
REVOKE UPDATE, DELETE ON documento_version FROM asi_app;
REVOKE DELETE ON documento, documento_asistencia FROM asi_app;
