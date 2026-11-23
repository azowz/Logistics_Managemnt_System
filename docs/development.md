# دليل التطوير

كل أوامر Python وCompose الخلفية أدناه تُنفذ من `mesaar-backend/` بعد الفصل.
للتطبيق المستقل وأوامر البناء والاختبار راجع [دليل الواجهة](../mesaar-frontend/README.md).

## 1. المتطلبات

- Python 3.11 في CI وصورة Docker؛ اختُبر التطوير المحلي على Python 3.12.10.
- PostgreSQL 16 وRedis 7 (عبر `docker compose up -d --wait db redis` أو تثبيت محلي).
- اعتماديات التطوير والاختبار والجودة في `requirements-dev.txt` وتشمل اعتماديات التشغيل.
- لتطبيق السائق: Node.js وnpm (انظر [mobile/README.md](../mesaar-frontend/README.md)).

```bash
python -m venv .venv && source .venv/bin/activate
python -m pip install -r requirements-dev.txt
cp .env.example .env
python -m alembic upgrade head
python -m uvicorn app.main:app --reload --reload-dir app
```

على Windows يمكن العمل دون تفعيل البيئة إن منعت سياسة PowerShell تشغيل Activate.ps1:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
$env:DEBUG = "false"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --reload-dir app
```

جهّز `.env` وPostgreSQL ودور التطبيق وطبّق الترحيلات بالمفسر نفسه قبل الطلبات. متغيرات
النظام تتقدم على `.env`؛ قيمة `DEBUG=release` مثلًا غير صالحة. عند ModuleNotFoundError،
استخدم `.\.venv\Scripts\python.exe -m pip check` وأعد تثبيت ملف الاعتماديات كاملًا في
البيئة نفسها. تشغيل `uvicorn` أو`pip` من بيئتين مختلفتين لا يثبت حزم العملية المطلوبة.

## 2. متغيرات البيئة

تُقرأ من البيئة ثم من `.env` (`extra=ignore`). القيم الافتراضية من `app/core/config.py`؛
عمود «المثال» من `.env.example` عند اختلافه.

| المتغير | الافتراضي | ملاحظات |
| --- | --- | --- |
| `DATABASE_URL` | `postgresql+psycopg2://postgres:postgres@localhost:5432/logistics` | المثال: `mesaar_app:mesaar_app@localhost:5432/mesaar`؛ يحتاج Bootstrap وفق operations.md |
| `SECRET_KEY` | `change-this-secret-key` | 32 حرفًا على الأقل؛ يوقّع JWT ويشتق مفتاح تشفير أسرار Webhooks. مرفوض في الإنتاج إن بدأ بـ `change-me`/`change-this` |
| `ENVIRONMENT` | `development` | `development`، `staging`، `production`، `test` |
| `DEBUG` | `false` | |
| `APP_NAME` / `APP_VERSION` | `Mesaar Logistics Operations API` / `1.0.0` | |
| `API_V1_PREFIX` | `/v1` | |
| `CORS_ORIGINS` | أصول localhost و127.0.0.1 على 8081 | JSON array أو قائمة مفصولة بفواصل؛ أصول HTTPS صريحة للنشر و`*` مرفوض في الإنتاج |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `60` (5–1440) | المثال: 30 |
| `REFRESH_TOKEN_EXPIRE_MINUTES` | `20160` (14 يومًا) | |
| `TOKEN_ALGORITHM` | `HS256` | القيمة الوحيدة المسموحة |
| `BCRYPT_WORK_FACTOR` | `12` (8–16) | |
| `JWT_ISSUER` / `JWT_AUDIENCE` | `mesaar` / `mesaar-clients` | معرّفة في الإعدادات لكن لا تُضاف ولا يُتحقق منها في التوكنات حاليًا |
| `LOG_LEVEL` / `LOG_JSON` | `INFO` / `true` | اجعل `LOG_JSON=false` للتطوير المحلي |
| `REQUEST_ID_HEADER` / `TENANT_HEADER` | `X-Request-ID` / `X-Tenant-ID` | |
| `PROMETHEUS_ENABLED` | `true` | |
| `REDIS_URL` | `redis://localhost:6379/0` | التوكنات وقائمة الإلغاء |
| `CACHE_TTL_SECONDS` | `300` | |
| `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND` | Redis `/1` / `/2` | |
| `CELERY_TASK_MAX_RETRIES` / `CELERY_TASK_DEFAULT_RETRY_DELAY` | `3` / `5` | |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` / `DB_POOL_TIMEOUT` / `DB_POOL_RECYCLE_SECONDS` / `DB_ECHO` | `5` / `10` / `30` / `1800` / `false` | لا تُطبَّق إعدادات الـ Pool على SQLite |

خارج الإعدادات: `TEST_DATABASE_URL` (يفعّل اختبارات PostgreSQL)، و`EXPO_PUBLIC_API_URL` /
`EXPO_PUBLIC_USE_MOCK` لتطبيق السائق.

## 3. الاختبارات

### الحزمة الافتراضية (SQLite)

```bash
python -m pytest -q
```

- `tests/conftest.py` يضبط `DATABASE_URL` على SQLite في الذاكرة و`SECRET_KEY` و`ENVIRONMENT=test`
  **قبل** استيراد `app` (المحرك يُبنى عند الاستيراد).
- قواعد تجميع خاصة بـ SQLite: `JSONB` → `JSON`، وتجاهل قيود CHECK التي تستخدم regex (`~`) —
  دون تعديل `Base.metadata`.
- مساعدات كل مجال في `tests/<domain>_sqlite.py` مبنية على `tests/sqlite_support.py`
  (`make_sqlite_engine`، `seed_tenant_user`).
- Redis والمزودون الخارجيون يُستبدلون بـ mocks.
- كثير من اختبارات الخدمات تُرقّع `app.services.<module>.get_current_tenant`؛ عند نقل دوال
  السياق بين الوحدات حدّث هذه الترقيعات.

### اختبارات PostgreSQL (العزل، الأحداث، الترحيلات)

تُتخطى ما لم يكن `TEST_DATABASE_URL` (و`DATABASE_URL` لاختبار الأحداث) يشير إلى PostgreSQL.
**هذه الاختبارات تنفّذ `drop_all`/`create_all`** — استخدم قاعدة مؤقتة فقط، وبدور غير superuser،
وإلا تصبح اختبارات RLS بلا معنى.

```bash
# مثال: Cluster مؤقت معزول على منفذ مختلف
initdb -D /tmp/mesaar-pg -U postgres -A trust && pg_ctl -D /tmp/mesaar-pg -o "-p 55432" -w start
psql -h localhost -p 55432 -U postgres -c "CREATE ROLE mesaar_app LOGIN PASSWORD 'mesaar_app' NOSUPERUSER NOBYPASSRLS;" \
     -c "CREATE DATABASE mesaar OWNER mesaar_app;"
export DATABASE_URL=postgresql+psycopg2://mesaar_app:mesaar_app@localhost:55432/mesaar
export TEST_DATABASE_URL=$DATABASE_URL
python -m pytest -q
```

### الترحيلات وفحص الانحراف

```bash
python -m alembic upgrade head
python -m alembic check        # يجب أن يطبع: No new upgrade operations detected.
```

`alembic check` يعمل في CI؛ إذا فشل فالنماذج والترحيلات غير متطابقة.

## 4. الجودة والتنسيق

```bash
python -m ruff check .
python -m black --check app
python -m mypy app
```

Black بطول100 هو Formatter المعتمد في `pyproject.toml`، وRuff للفحص؛ لا تستخدم
`ruff format --check` بوابة بديلة، إذ تختلف قواعده عن Black. Mypy ناجح محليًا وإلزامي
في CI. تنفذ CI الترحيلات وفحص الانحراف وPytest بدور غير خارق مع PostgreSQL وRedis.

## 5. سير العمل

### تعديل المخطط

1. عدّل النموذج في `app/models/`.
2. `make revision MSG="وصف التغيير"` (يتطلب قاعدة مرحّلة؛ Black يُنسّق الملف تلقائيًا).
3. راجع الملف المولَّد يدويًا: RLS للجداول الجديدة، `IF NOT EXISTS` عند الحاجة، `downgrade` سليم.
4. **لا تعدّل ترحيلًا مطبَّقًا مسبقًا**؛ أضف ترحيلًا جديدًا دائمًا.
5. `alembic upgrade head && alembic check && alembic downgrade -1 && alembic upgrade head`.

### إضافة ميزة أو مجال

اتبع الخطوات في [architecture.md §10](architecture.md#10-إضافة-مجال-جديد). القواعد الأساسية:

- الموجّه رفيع: تحقق، صلاحيات، استدعاء خدمة، تحويل الاستجابة.
- الخدمة تملك المعاملة وتصدر الأحداث بعد `flush` وقبل `commit`.
- المستودع بلا `commit` ولا أحداث.
- انتقالات الحالة عبر `ALLOWED_TRANSITIONS` في `*_policies.py` فقط.
- أي معرّف كيان آخر يأتي من العميل يجب التحقق من انتمائه لنفس المستأجر.
- أضف اختبار Regression لكل إصلاح خطأ.

### أسلوب الكود

- Black بطول سطر 100، Type hints للدوال العامة، و`from __future__ import annotations`.
- الأسماء بالإنجليزية؛ التعليقات قصيرة وتشرح «لماذا» (قاعدة عمل، حد معاملة، قيد أمني)، لا «ماذا».
- يجوز كتابة تعليقات قواعد الأعمال بالعربية.
- التواريخ عبر `app.common.datetime.utcnow()` (timezone-aware).
- المدققات المشتركة في `app/schemas/common.py` (`validate_currency_code`، `require_aware_datetime`)،
  وenum الأعمدة بـ `values_callable=enum_values`.

### التوثيق

- التوثيق بالعربية مع إبقاء المعرّفات والأوامر بالإنجليزية.
- حدّث [status.md](status.md) عند إضافة أو إكمال ميزة؛ و[domains.md](domains.md) عند تغيير قاعدة عمل.
- القرار المعماري الجديد = ADR جديد في [adr/](adr/README.md)؛ لا تُعدَّل القرارات المعتمدة بل تُستبدل.
