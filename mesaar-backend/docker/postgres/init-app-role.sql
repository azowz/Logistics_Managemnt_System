-- بيئة Compose المحلية فقط. يعمل تلقائيًا عند إنشاء volume جديد.
-- حساب POSTGRES_USER حساب إدارة؛ التطبيق والترحيلات يحتاجان دورًا يخضع لـRLS.
SELECT 'CREATE ROLE mesaar_app LOGIN PASSWORD ''mesaar_app'' NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS'
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mesaar_app')
\gexec

GRANT USAGE, CREATE ON SCHEMA public TO mesaar_app;
-- تدعم أيضًا إعادة تشغيل السكربت على volume محلي سبق إنشاؤه بحساب الإدارة.
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO mesaar_app;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO mesaar_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO mesaar_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO mesaar_app;
