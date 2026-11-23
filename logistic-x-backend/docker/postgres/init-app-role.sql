-- بيئة Compose المحلية فقط. يعمل تلقائيًا عند إنشاء volume جديد.
-- حساب POSTGRES_USER حساب إدارة؛ التطبيق والترحيلات يحتاجان دورًا يخضع لـRLS.
SELECT 'CREATE ROLE logistic_x_app LOGIN PASSWORD ''logistic_x_app'' NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS'
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'logistic_x_app')
\gexec

GRANT USAGE, CREATE ON SCHEMA public TO logistic_x_app;
-- تدعم أيضًا إعادة تشغيل السكربت على volume محلي سبق إنشاؤه بحساب الإدارة.
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO logistic_x_app;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO logistic_x_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO logistic_x_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO logistic_x_app;
