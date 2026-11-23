# المعمارية (Architecture)

يصف هذا المستند البنية **الحالية كما هي في الكود**. القرارات وأسبابها في [adr/](adr/README.md)،
وتفاصيل كل مجال في [domains.md](domains.md)، وقاعدة البيانات في [database.md](database.md).

## 1. نظرة عامة

```text
 العملاء (تطبيق السائق، لوحات مستقبلية، شركاء API)
          │ HTTPS + JWT / API Key
          ▼
 ┌───────────────────────── api (FastAPI / gunicorn) ─────────────────────────┐
 │ Middleware: CORS → RequestContext (request_id، X-Tenant-ID، سجل الوصول)     │
 │ routes (/v1) → services (+ policies) → repositories → SQLAlchemy Session   │
 │                          │ في نفس المعاملة                                  │
 │                          └──► event_store (Outbox)                          │
 └────────────────────────────────────┬────────────────────────────────────────┘
                                      │ PostgreSQL (RLS لكل مستأجر)
 ┌──────────────── worker / beat (Celery + Redis) ─────────────┐
 │ relay_outbox (30s) → EventBus → المستهلكون:                 │
 │   notifications · analytics (Projections) · webhooks        │
 │ projection_health_check (5m) · webhook_delivery_sweep (60s) │
 └─────────────────────────────────────────────────────────────┘
```

العمليات: `api` و`worker` و`beat` تشترك في نفس الصورة (Dockerfile) ونفس الحزمة `app/`.
Redis يخدم ثلاثة أغراض بقواعد منفصلة: التوكنات وقائمة الإلغاء (0)، Broker لـ Celery (1)، النتائج (2).

## 2. الطبقات وقواعد الاعتماد

| الطبقة | المجلدات | المسؤولية | لا يجوز لها |
| --- | --- | --- | --- |
| العرض (Presentation) | `app/api/` | التحقق من المدخلات بالمخططات، المصادقة والأدوار، تحويل النتائج إلى استجابات | احتواء قواعد أعمال أو استعلامات |
| العقود | `app/schemas/` | نماذج Pydantic للطلب والاستجابة، مدققات مشتركة في `schemas/common.py` | استيراد services أو repositories |
| التطبيق/المجال | `app/services/` | حالات الاستخدام، قواعد الأعمال، آلات الحالات (`*_policies.py`)، حدود المعاملة، إصدار الأحداث | استيراد FastAPI أو `app/api` |
| الوصول للبيانات | `app/repositories/` | الاستعلامات والحفظ دون `commit` (`base.py`: `BaseRepository`, `coerce_uuid`) | قواعد أعمال أو إصدار أحداث |
| النماذج | `app/models/`، `app/db/` | الجداول والقيود والـ Mixins وسياق المستأجر | الاعتماد على الطبقات الأعلى |
| البنية التحتية المشتركة | `app/core/`، `app/events/`، `app/observability/`، `app/common/` | الإعدادات، الأمان، الأحداث، السجلات، الأدوات | — |
| المستهلكون والعمّال | `app/notifications/`، `app/analytics/`، `app/integrations/`، `app/projections/`، `app/workers/` | معالجة الأحداث والمهام الدورية | الاستدعاء من الموجّهات مباشرة |

الاتجاه دائمًا من الأعلى للأسفل: `api → services → repositories → models`. الاستثناءات الموثقة:

- موجّهات `users` و`drivers` و`vehicles` و`warehouses` القديمة تستدعي المستودعات مباشرة،
  ومستودعاتها تنفّذ `commit` بنفسها (نمط قديم، انظر [status.md](status.md#الديون-التقنية)).
- `app/core/security.py` يستورد `UserRepository` لتحميل المستخدم أثناء المصادقة.

## 3. دورة الطلب

1. **`RequestContextMiddleware`** (`app/api/middleware/request_context.py`): يحدد `request_id`
   (من `X-Request-ID` أو UUIDv7 جديد)، ويقرأ `X-Tenant-ID` إن وُجد، ويسجل سطر الوصول، ويعيد
   ضبط كل ContextVars في `finally`.
2. **المصادقة** (`app/core/security.py`):
   - `_authenticate` (sync، داخل threadpool): يفك JWT، ويتحقق من قائمة الإلغاء في Redis
     (`denylist:{jti}`)، ويحمّل المستخدم النشط تحت نطاق مستأجر التوكن.
   - `get_current_user` (**async عمدًا**): يربط `tid` ومعرّف المستخدم بسياق الطلب نفسه.
     FastAPI ينفّذ الاعتماديات sync داخل **نسخة** من السياق، فأي ضبط هناك يضيع؛ لذلك
     الربط يتم في الاعتمادية async. يجب تطابق مستأجر التوكن مع المستخدم المحفوظ؛ التوكن
     القديم بلا `tid` يحل مستأجر المستخدم ثم يضيّق GUC في المعاملة نفسها. الترويسة لا تثبت الهوية.
   - الشركاء: `get_current_api_key_partner` (sync) ثم `bind_api_key_partner` (async) بنفس المنطق.
   - الأدوار: `require_roles(UserRole.ADMIN, ...)` في كل موجّه (لا يوجد نظام Permissions أدق).
3. **الموجّه** يبني `XxxService(session)` ويستدعي حالة الاستخدام.
4. **الخدمة** تتبع النمط الموحد:

   ```text
   tenant_id = _tenant_id()          # من السياق؛ يرفض الطلب إن لم يوجد
   تحميل الـ Aggregate → التحقق من الملكية (tenant_id) → قواعد الأعمال/آلة الحالات
   تعديل الكيان → session.flush()
   _emit(DomainEvent) → EventEnvelope.create() → EventStoreRepository.append()
   session.commit()                  # الكيان والحدث في معاملة واحدة
   ```

5. **أخطاء التطبيق والمجال والتحقق** تُحوَّل مركزيًا في `app/core/exceptions.py` إلى غلاف مشترك
   `{"error": {code, message, details, request_id}}` (انظر [api.md](api.md#5-الأخطاء)).

## 4. تعدد المستأجرين (Multi-Tenancy)

- جداول بيانات المستأجر تحمل `tenant_id NOT NULL` وسياسة RLS `tenant_isolation`؛ تستثنى
  `tenants` وجداول بنية تحتية محددة كما في [قاعدة البيانات](database.md).
- مستمع `after_begin` في `app/db/session.py` ينفّذ في بداية **كل معاملة**
  `set_config('app.current_tenant', ..., true)` و`app.current_user_id` (نطاق المعاملة فقط،
  فلا تتسرب القيمة عبر اتصالات الـ Pool).
- المستأجر الصفري `00000000-0000-0000-0000-000000000000` هو نطاق المنصة ويرى كل الصفوف؛
  ويُطبَّق تلقائيًا عند غياب مستأجر في السياق (مسارات تسجيل الدخول، العمّال قبل اختيار المستأجر).
- المستودعات لا تضيف فلتر `tenant_id` وتعتمد على RLS؛ لذلك **يجب** أن يتصل التطبيق بدور
  PostgreSQL غير superuser وبدون `BYPASSRLS`. الخدمات تتحقق أيضًا من `obj.tenant_id` عندما
  يأتي معرّف كيان آخر من العميل (`_owned` / `_require_tenant_owned`).
- العمّال يستخدمون `session_scope(tenant_id)` الذي يربط المستأجر ويعيد ضبطه بعد الانتهاء.

## 5. الأحداث (Event-Driven, Transactional Outbox)

**المصدر:** `app/events/` و`app/models/event_store.py` و`app/repositories/event_store_repository.py`.

| المكوّن | الملف | الدور |
| --- | --- | --- |
| `DomainEvent` + `@register_event` | `events/domain_event.py`، `events/registry.py`، `events/*_events.py` | تعريف الأحداث وتسجيلها بالاسم والإصدار؛ يدعم Upcasters (لا يوجد أي منها حاليًا، كل الأحداث v1) |
| `EventEnvelope` | `events/envelope.py` | `event_id` (UUIDv7 = مفتاح Idempotency)، `tenant_id`، `aggregate_type/id/version`، `event_type/version`، `payload`، `occurred_at`، `correlation_id`، `causation_id`، `user_id`، `metadata` |
| `event_store` | `models/event_store.py` | جدول Outbox؛ قيد فريد على `(aggregate_id, aggregate_version)` يمنع الكتابة المتزامنة لنفس الإصدار (`ConcurrencyConflictError` → HTTP 409) |
| Relay | `events/relay.py` | مهمة `mesaar.relay_outbox` كل 30 ثانية: يقرأ الدفعة تحت نطاق المنصة، وينشر كل حدث في **معاملة مستقلة بنطاق مستأجره**، ثم يختمه `published_at`. بعد 5 محاولات نقل فاشلة يُنقل إلى `dead_letter_events` |
| `EventBus` | `events/bus.py` | يوزّع الحدث على المعالجات المسجلة (notifications, analytics, webhooks) |
| `EventDispatcher` | `events/dispatcher.py` | Idempotency عبر `processed_events (consumer, event_id)`، إعادة المحاولة 3 مرات بتراجع أسي (0.2s، حد أقصى 5s)، ثم Dead Letter دون إيقاف بقية الأحداث |

الضمانات الفعلية:

- **عدم فقدان الأحداث:** الحدث يُكتب مع الكيان في نفس المعاملة؛ لا يوجد Dual-Write.
- **التسليم At-Least-Once:** المستهلكون يجب أن يكونوا Idempotent (مضمون عبر `processed_events`).
- **الترتيب:** `aggregate_version` متسلسل لكل Aggregate؛ الـ Relay يقرأ بالترتيب لكنه لا يحجز
  الصفوف (`SKIP LOCKED` غير مستخدم)، لذا تشغيل أكثر من beat أو دفعات متداخلة قد يكرر النشر —
  تُكتشف التكرارات في `processed_events` لكن قد تُحتسب فشلًا. شغّل beat واحدًا.
- **إعادة التشغيل (Replay):** `dead_letter_events` يدعم إعادة الحدث عبر
  `EventStoreRepository.mark_dead_letter_replayed`.
- **عقود الأحداث:** أسماء الأحداث `<Aggregate><PastTenseVerb>` (مثل `ShipmentDelivered`)؛ أي
  تغيير غير متوافق يتطلب إصدارًا جديدًا + Upcaster، لا تعديل الإصدار القائم.

## 6. القراءات التحليلية (CQRS)

- الكتابة تمر عبر الخدمات والجداول المعيارية؛ القراءات التحليلية من جداول `proj_*` يحدّثها
  مستهلك التحليلات (`app/analytics/handlers.py` → `ProjectionService`) من الأحداث.
- كل إسقاط قابل لإعادة البناء من `event_store` (`POST /v1/analytics/projections/rebuild`، للمدير فقط)
  عبر `app/projections/engine.py`.
- `projection_health` + مهمة `projection_health_check` تصنّف الإسقاطات (healthy/stale/error)
  دون إعادة بناء تلقائية.

## 7. المهام الخلفية (Celery)

`app/workers/celery_app.py` (`acks_late`، `prefetch_multiplier=1`، مهلة 300s، JSON فقط) و`app/workers/tasks.py`:

| المهمة | الجدولة | الوظيفة |
| --- | --- | --- |
| `mesaar.relay_outbox` | كل 30s (`batch_size=100`) | نشر أحداث Outbox |
| `mesaar.projection_health_check` | كل 5 دقائق | تصنيف حالة الإسقاطات |
| `mesaar.webhook_delivery_sweep` | كل 60s (`batch_per_tenant=100`) | إعادة محاولة تسليم Webhooks المستحقة |
| `mesaar.ping` | عند الطلب | فحص تشخيصي |

خيار `expires` في الجدولة يسقط المهمة إن لم **تبدأ** خلال المهلة فقط؛ وهو ليس حماية من التداخل.

## 8. الأمان

| الضابط | التنفيذ |
| --- | --- |
| كلمات المرور | bcrypt (`BCRYPT_WORK_FACTOR`، افتراضي 12) عبر passlib |
| Access Token | JWT HS256 (الخوارزمية مثبتة)، مطالبات `sub`، `role`، `tid`، `jti`، `exp`، `iat` |
| Refresh Token | معرّف معتم في Redis (`refresh:{id}`) يُستهلك ذريًا بـ `GETDEL` (يمنع إعادة الاستخدام) |
| تسجيل الخروج | `denylist:{jti}` في Redis حتى انتهاء صلاحية التوكن؛ تعطل Redis يُسجَّل ولا يمنع المصادقة (Fail-Open) |
| الأدوار | `admin`، `manager`، `driver`، `client` عبر `require_roles` |
| مفاتيح الشركاء | bcrypt للمفتاح، نطاقات (scopes)، قائمة IP مسموحة، HMAC-SHA256 لتوقيع الطلبات الواردة مع نافذة زمنية ±300s |
| أسرار Webhooks | مشفرة بـ Fernet بمفتاح مشتق من `SECRET_KEY` (مزود KMS قابل للتوصيل غير مفعّل) |
| عناوين Webhooks | HTTPS إلزامي، ورفض عناوين loopback/الشبكات الخاصة/link-local و`localhost`/`*.internal`/`*.local` |
| إعدادات الإنتاج | رفض `SECRET_KEY` الافتراضي و`CORS_ORIGINS=*` عند `ENVIRONMENT=production` |

الثغرات المعروفة التي لم تُعالج بعد موثقة في [status.md](status.md#المخاطر-الأمنية-المفتوحة).

## 9. المراقبة (Observability)

- السجلات: loguru، JSON عند `LOG_JSON=true`، وكل سطر يحمل `request_id`؛ سطر وصول لكل طلب.
- المقاييس: `prometheus-client` عبر Middleware و`/metrics`، ومقاييس خاصة بالأحداث في `app/events/metrics.py`.
- الحالة: `/health/live` (العملية فقط)، `/health/ready` (PostgreSQL + Redis، 503 عند الفشل)، `/health`.

## 10. إضافة مجال جديد

1. **النموذج:** `app/models/<domain>.py` بـ `tenant_id` + Mixins (`TimestampMixin`، `AuditMixin`،
   `SoftDeleteMixin`) و`version_id_col` إن كان قابلًا للتعديل المتزامن، وenums بـ
   `values_callable=enum_values`. صدّره في `app/models/__init__.py`.
2. **الترحيل:** `make revision MSG="<domain> domain"` ثم راجع الملف، وأضف `ENABLE`/`FORCE ROW LEVEL SECURITY`
   وسياسة `tenant_isolation` بنفس صيغة الترحيل `0018`. تأكد أن `alembic check` نظيف.
3. **المستودع:** `app/repositories/<domain>_repository.py` يرث `BaseRepository`، دون `commit`.
4. **آلة الحالات:** `app/services/<domain>_policies.py` بخريطة `ALLOWED_TRANSITIONS`.
5. **الأحداث:** `app/events/<domain>_events.py` بـ `@register_event`، واستيراده في `app/events/__init__.py`.
6. **الخدمة:** `app/services/<domain>_service.py` بالنمط في §3 (الخدمة تملك `commit`).
7. **المخططات والموجّه:** `app/schemas/<domain>.py` و`app/api/routes/<domain>.py` بأدوار صريحة،
   ثم أضفه في `app/api/v1/router.py` ووسم OpenAPI في `app/main.py`.
8. **الاختبارات:** نموذج/مستودع/خدمة/آلة حالات/مسارات (SQLite عبر `tests/sqlite_support.py`) واختبار
   عزل على PostgreSQL إن أضفت سياسة RLS.
9. **التوثيق:** قسم في [domains.md](domains.md) وجداول في [database.md](database.md) وتحديث [status.md](status.md).
