# التشغيل والنشر والمراقبة

بعد الفصل، تُنفذ أوامر الخلفية التالية من `logistic-x-backend/` بملف بيئته الخاص.
للتشغيل المتكامل من الجذر وبناء الواجهة المستقلة راجع [README](../README.md)
و[دليل الواجهة](../logistic-x-frontend/README.md). تبقى مسارات `app/` نسبية لمجلد الخلفية.

يوفر المستودع Dockerfile و Compose للتطوير و Celery. لا توجد Kubernetes أو Terraform أو
خدمة TLS أو نسخ احتياطي أو Prometheus Server مضمنة. راجع [المخطط](diagrams/deployment.mmd).

## العمليات

| العملية | التشغيل |
| --- | --- |
| API | أمر الصورة Gunicorn مع Uvicorn Workers؛ WEB_CONCURRENCY يحدد العدد والافتراضي 4 |
| العامل | python -m celery -A app.workers.celery_app worker --loglevel=info |
| المجدول | python -m celery -A app.workers.celery_app beat --loglevel=info؛ نسخة واحدة |
| الترحيلات | python -m alembic upgrade head؛ خطوة نشر مستقلة |

الصورة على Python3.11، تعمل بمستخدم غير Root، وفحصها /health/live.
أنشئ .env كما في [README](../README.md)، ثم:

```bash
docker compose build api
docker compose up -d --wait db redis
docker compose run --rm --no-deps api python -m alembic upgrade head
docker compose up -d api worker beat
docker compose logs -f api worker beat
docker compose down
```

يحفظ الإيقاف البيانات في Named Volumes. config يثبت تركيب الإعداد فقط؛ نتائج البناء
والتشغيل الفعلي للحاويات في [تقرير الفصل](../SEPARATION_REPORT.md).

## دور PostgreSQL و Volumes القائمة

حساب POSTGRES_USER=logistic_x حساب إدارة Superuser. تتصل api/worker/beat بـ**logistic_x_app**
ذي NOSUPERUSER NOBYPASSRLS لفرض RLS. ينشئه
[init-app-role.sql](../logistic-x-backend/docker/postgres/init-app-role.sql) تلقائيًا عند تهيئة Volume جديد؛
التهيئة لا تعاد عند استخدام Volume قائم.

لـ Volume تطوير قائم شغّل السكربت نفسه دون حذف البيانات. PowerShell:

```powershell
Get-Content docker/postgres/init-app-role.sql | docker compose exec -T db psql -U logistic_x -d logistic_x -v ON_ERROR_STOP=1
```

Bash:

```bash
docker compose exec -T db psql -U logistic_x -d logistic_x -v ON_ERROR_STOP=1 < docker/postgres/init-app-role.sql
```

السكربت يهيئ الدور والصلاحيات الحالية والافتراضية ويمكن إعادة تشغيله؛ **لا ينقل ملكية
الجداول القديمة**. إذا كانت مملوكة لـ logistic_x فقد تحتاج الترحيلات المستقبلية التي تنفذ
DDL إلى مالكها. استخدم حساب المالك للترحيل فقط أو خطة مستقلة لنقل الملكية، وأبق اتصال
التطبيق محدودًا. مثال محلي لقاعدة يملك جداولها logistic_x:

```bash
docker compose run --rm --no-deps -e DATABASE_URL=postgresql+psycopg2://logistic_x:logistic_x@db:5432/logistic_x api python -m alembic upgrade head
```

لا تستخدم حذف Volume علاجًا للصلاحيات. تحقق من دور التطبيق:
`SELECT current_user, rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user`.
كلمات المرور هنا للتطوير؛ جهّز أسرار النشر وأدواره لكل بيئة.

## متطلبات الإنتاج

- ENVIRONMENT=production و DEBUG=false وسر عشوائي وأصول CORS صريحة. يرفض الإعداد
  Placeholder و Wildcard؛ دخول الهاتف معطل 501 حتى توصيل OTP.
- دور تطبيق غير خارق دون BYPASSRLS؛ ترحيلات وفحص انحراف ونسخة احتياطية مجربة.
- Redis دائم لحفظ Refresh Tokens و Denylist، مع مراقبة عطله؛ فحص الإلغاء يتجاوزه بتحذير.
- LOG_JSON=true وتجميع stdout، وحماية /metrics من الوصول العام.
- Beat واحد؛ Relay و Webhook Sweep لا يوفران حجزًا كاملًا ضد التداخل.
- سجّل HttpWebhookProvider عبر set_webhook_provider عند إقلاع العامل للتسليم الخارجي؛
  الافتراضي provider_not_configured ولا يرسل شبكة.
- مع عمليات API متعددة سجّل RedisRateLimitBackend عبر set_inbound_rate_limiter؛ الافتراضي
  محلي للعملية. جهّز ضوابط Egress لمخاطر DNS/SSRF.
- تغيير SECRET_KEY يبطل JWT ويغير مفتاح فك أسرار Webhooks؛ يحتاج خطة تدوير. مزود KMS
  قابل للتوصيل عبر Secret Provider، لكنه غير مسجل تلقائيًا.

## المراقبة والأعطال

| الإشارة/العَرَض | المصدر أوالإجراء |
| --- | --- |
| Liveness | /health/live؛ العملية فقط |
| Readiness | /health/ready؛ PostgreSQL/Redis مع 200 أو 503 |
| لقطة شاملة | /health؛ 200 والحالة في الجسم |
| المقاييس | /metrics عند التفعيل؛ HTTP والأحداث |
| السجلات | stdout مع request_id؛ لا تسجل أسرار اتصال Celery |
| صحة الإسقاط | /v1/analytics/projections/health وفحص دوري؛ لا Rebuild آلي |
| العامل | python -m celery -A app.workers.celery_app inspect ping |
| No module named loguru/redis/... | فعّل البيئة الصحيحة وثبت requirements.txt كاملًا، أو requirements-dev.txt للتطوير، ثم python -m pip check |
| DEBUG=release | متغيرات النظام تتقدم على.env؛ صححها مثل $env:DEBUG="false" في PowerShell |
| خطأ SECRET_KEY أو CORS | تحقق من طول السر والبيئة و Placeholder والأصول الصريحة |
| role logistic_x_app does not exist | أعد Bootstrap أعلاه للـ Volume القديم؛ لا تحذف البيانات |
| must be owner أثناء الترحيل | استخدم مالك الجداول للترحيل أو خطط لنقل الملكية؛ التطبيق يبقى محدودًا |
| بيانات مستأجر آخر | افحص دور الاتصال وسياق المستأجر؛ Superuser و BYPASSRLS يتجاوزان العزل |
|409 تزامن | أعد تحميل الكيان قبل إعادة المحاولة |
| إشعار/إسقاط لا يتحدث | تحقق من Worker و Beat و Relay والأحداث التي published_at IS NULL |
| Dead Letter | افحص failure_reason، أصلح السبب، ثم Replay مع منع التكرار؛ لا تحذف التاريخ |
| Celery على Windows | استخدم --pool=solo للتطوير؛ للنشر حاويات Linux |
| alembic check يفشل | طابق النماذج بترحيل جديد؛ لا تعدل تاريخًا مطبقًا |
