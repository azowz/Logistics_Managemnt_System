# قاعدة البيانات — Mesaar Backend

يصف هذا المستند طبقة البيانات **كما هي في الشيفرة الحالية**: النماذج في `app/models/`، والبنية التحتية في `app/db/`، وسلسلة الترحيلات في `migrations/versions/` (من `0001` حتى `0019`). أما المستندات في `docs/archive/` (ومنها `03-database-architecture.md` و`10-final-erd-review.md`) فهي سجل تاريخي لمراحل التصميم، وحيثما تعارضت مع هذا المستند فالمرجع هو الشيفرة.

---

## 1. نظرة عامة (Overview)

| البند | القيمة الفعلية |
|---|---|
| محرك قاعدة البيانات | PostgreSQL 16 (صورة `postgres:16` في `docker-compose.yml` وفي CI) |
| ORM | SQLAlchemy 2 (`DeclarativeBase`، `Mapped[...]`، `mapped_column`) |
| الترحيلات | Alembic، سلسلة خطية مكتوبة يدويًا في `migrations/versions/` |
| المشغّل (Driver) | `psycopg2` (`postgresql+psycopg2://...`) |
| العزل | Multi-tenant على مخطط مشترك (Shared Schema) مع Row-Level Security |
| عدد الجداول | 52 جدولًا (49 جدولًا خاضعًا لـ RLS + `tenants` + `processed_events` + `outbox_relay_state`) |

### اصطلاح تسمية القيود (Naming Convention)

يعرّف `app/db/base.py` كائن `MetaData` موحّدًا تُشتق منه أسماء القيود تلقائيًا، فتبقى ثابتة بين البيئات وبين `create_all` والترحيلات:

| النوع | النمط | مثال |
|---|---|---|
| `pk` | `pk_%(table_name)s` | `pk_tenants` |
| `fk` | `fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s` | `fk_shipments_order_id_orders` |
| `uq` | `uq_%(table_name)s_%(column_0_name)s` | `uq_tenants_slug` |
| `ix` | `ix_%(column_0_label)s` | `ix_shipments_tenant_id` |
| `ck` | `ck_%(table_name)s_%(constraint_name)s` | `CheckConstraint(..., name="status")` ← `ck_customers_status` |

ملاحظة: القيود المركّبة (Composite) تُسمّى صراحةً في النماذج (مثل `uq_users_tenant_id_email`) لأن النمط الافتراضي لا يأخذ إلا العمود الأول. ويجب ألا يتجاوز الاسم 63 حرفًا (حد PostgreSQL)، وهو ما يتحقق منه `tests/test_migrations_postgresql.py`.

### المفاتيح الأساسية (Primary Keys)

- **الجداول التشغيلية** (47 جدولًا): `UUID` بقيمة افتراضية `uuid.uuid4` تُولَّد في جهة العميل.
- **جداول العمود الفقري للأحداث** وفق ADR-007: `event_store.event_id` و`dead_letter_events.id` و`outbox_relay_state.id` و`audit_log.id` تستخدم **UUIDv7** عبر `app.db.uuidv7.uuid7` (مولّد RFC-9562 بلغة Python، مرتب زمنيًا ورتيب Monotonic داخل العملية، آمن مع الخيوط Thread-safe).
- `processed_events` مفتاحها مركّب `(consumer, event_id)`.
- `app/db/base_model.BaseModel` صنف مجرّد (`__abstract__ = True`) يوفّر `id` من نوع UUIDv7، وهو الآلية التي يقرّها ADR-007 للنماذج المستقبلية، **لكن لا يرث منه أي نموذج حاليًا**. وينص تعليق الملف صراحةً على عدم نقل النماذج القائمة إليه لأن ذلك يغيّر القيمة الافتراضية للمفتاح.

### الأنواع

- **الوقت**: كل أعمدة الوقت `DateTime(timezone=True)` أي `timestamptz`، وأعمدة `created_at`/`updated_at` لها `server_default=now()`. الاستثناء المقصود هو أعمدة `Date` في جداول الإسقاط (`period_date`).
- **المال والكميات**: `Numeric` دائمًا وليس `Float`، مثل `Numeric(12, 2)` للأوزان والأسعار و`Numeric(9, 6)` للإحداثيات، وتُربط في النماذج المالية بـ `Decimal`. العملة عمود `currency_code` بطول 3 مع قيد CHECK بنمط ISO-4217 (`~ '^[A-Z]{3}$'`).
- **البيانات شبه المهيكلة**: `JSONB` (مثل `tenants.settings` و`event_store.payload` و`audit_log.old_row/new_row`).

---

## 2. الأنماط المشتركة (Mixins)

معرّفة في `app/db/mixins.py`:

| Mixin | الأعمدة | الاستخدام الفعلي |
|---|---|---|
| `TimestampMixin` | `created_at`, `updated_at` (timestamptz، `server_default=now()`، و`onupdate=now()` لـ `updated_at`) | كل الجداول التشغيلية وجداول الإسقاط |
| `SoftDeleteMixin` | `deleted_at` (nullable) + `is_deleted` و`soft_delete()` (idempotent) و`restore()` | 32 نموذجًا تجميعيًا (Aggregate) |
| `AuditMixin` | `created_by`, `updated_by` (UUID، nullable، بلا FK) | النماذج نفسها |
| `TenantMixin` | `tenant_id` NOT NULL مفهرس | **غير مستخدم في أي نموذج**؛ مُختبَر في `tests/test_mixins.py` فقط |

- **`deleted_by`** ليس جزءًا من أي Mixin، بل يُعرّف يدويًا في نماذج المجالات من `0006` فصاعدًا (customers وorders وshipments والمعدات والامتثال والتأمين والفوترة والإشعارات والتكامل). أما `tenants` و`users` و`drivers` و`vehicles` و`warehouses` فلا تملكه.
- **`tenant_id`** يُعرّف يدويًا في كل نموذج بالشكل `ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True`. وفي `event_store` و`dead_letter_events` و`audit_log` لا يحمل `index=True` لأن الفهارس المركّبة تبدأ به.
- **حذف الصفوف المؤرشفة**: لا يوجد مرشّح عام (Global Filter) لـ `deleted_at IS NULL`، فكل استعلام أو خدمة مسؤولة عن استبعاد الصفوف المحذوفة منطقيًا (Soft-Deleted).
- الجداول الملحقة (Append-only) مثل `shipment_tracking_events` و`invoice_lines` و`*_delivery_attempts` و`inbound_integration_events` وجداول `proj_*` لا تحمل SoftDelete ولا Audit.

### القفل التفاؤلي (Optimistic Locking)

كل نموذج يرث `SoftDeleteMixin` (32 نموذجًا) يعرّف:

```python
version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
__mapper_args__ = {"version_id_col": version}
```

وهي: `tenants`, `users`, `drivers`, `vehicles`, `warehouses`, `shipments`, `customers`, `orders`, `equipment_categories`, `equipment_models`, `equipment`، وجداول الامتثال الستة، وجداول التأمين الخمسة، وجداول الفوترة الستة (عدا `invoice_lines`)، و`notification_templates`, `notifications`, `integration_partners`, `webhook_subscriptions`.

يضيف SQLAlchemy الشرط `WHERE version = :old` إلى كل `UPDATE`، فإن لم يتأثر أي صف رفع `StaleDataError`، وتحوّله طبقة الـ API إلى `409 Conflict`. ويوجد على مستوى الأحداث خط حماية ثانٍ مستقل عن هذا: `UNIQUE(aggregate_id, aggregate_version)` في `event_store`.

### تخزين التعدادات (Enum Storage)

النمط المعتمد هو `SAEnum(..., native_enum=False, length=N, values_callable=enum_values)`:

- `native_enum=False` يعني أن العمود `VARCHAR(N)` وليس نوع `ENUM` في PostgreSQL.
- `enum_values` (في `app/models/enums.py`) يجعل SQLAlchemy يخزّن **القيمة** بأحرف صغيرة (`draft`) لا **الاسم** (`DRAFT`).
- قيد CHECK **لا** يولّده `SAEnum` (لأن `create_constraint` افتراضيًا `False` في SQLAlchemy 2)، بل يُعرّف صراحةً كـ `CheckConstraint("status IN ('draft', ...)", name="status")` في `__table_args__`، ويتكرر بالنص نفسه في الترحيلة.

**استثناءات قديمة (Legacy) تخزّن اسم العضو بأحرف كبيرة** لأنها لا تمرّر `values_callable`:

| العمود | القيم المخزّنة | قيد CHECK |
|---|---|---|
| `shipments.status` | `CREATED`, `READY`, `ASSIGNED`, `PICKED_UP`, `IN_TRANSIT`, `DELAYED`, ... | لا يوجد |
| `shipment_tracking_events.status` | كما سبق | لا يوجد |
| `shipment_tracking_events.event_type` | `STATUS_UPDATE`, `LOCATION_UPDATE`, ... | لا يوجد |
| `vehicles.status` | `ACTIVE`, `MAINTENANCE`, `DECOMMISSIONED` | لا يوجد |
| `users.role` | `ADMIN`, `MANAGER`, `DRIVER`, `CLIENT` | لا يوجد |

يؤكد ذلك أن الفهارس الجزئية في `0008` تقارن بقيم كبيرة (`status = 'READY'`). أما `sa.Enum(...)` في `0001_baseline.py` فيسرد قيمًا صغيرة، لكنه لا يُنشئ أي قيد، فلا أثر له على المخزَّن. **أي SQL يدوي أو تقرير على هذه الأعمدة يجب أن يستخدم الأحرف الكبيرة.** في المقابل يستخدم `shipments.priority` الذي أُضيف في `0008` القيم الصغيرة مع `ck_shipments_priority`.

---

## 3. العزل بين المستأجرين (Multi-Tenancy & RLS)

### النموذج

- جدول `tenants` (`slug` فريد، `status ∈ {active, suspended}`، `isolation_mode ∈ {shared, dedicated}`، `settings` JSONB).
- **المستأجر المنصّة (Platform Tenant)** هو `00000000-0000-0000-0000-000000000000`، ويُزرع (Seed) في ترحيلة `0003` بالاسم `platform` (`PLATFORM_TENANT_ID` في `app/db/tenant.py`).
- كل جدول مستأجر يحمل `tenant_id NOT NULL` + `FK → tenants.id ON DELETE RESTRICT` + فهرسًا، ويخضع لـ:

```sql
ALTER TABLE <t> ENABLE ROW LEVEL SECURITY;
ALTER TABLE <t> FORCE  ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON <t> USING (...) WITH CHECK (...);
```

- الجداول التي **لا** تخضع لـ RLS هي: `tenants` و`processed_events` و`outbox_relay_state` (جداول بنية تحتية بلا بيانات مستأجر).

### نص السياسة بعد الترحيلة 0018

```sql
USING (
  tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid
  OR NULLIF(current_setting('app.current_tenant', true), '')::uuid
     = '00000000-0000-0000-0000-000000000000'::uuid
)
WITH CHECK ( <same predicate> )
```

| قيمة `app.current_tenant` | النتيجة |
|---|---|
| UUID مستأجر | يرى صفوفه فقط، ولا يُسمح له بإدراج أو تعديل صف لمستأجر آخر (`WITH CHECK`) |
| nil-UUID (المنصّة) | يرى **كل** الصفوف ويكتب لأي مستأجر |
| غير مضبوطة (unset) | `NULL`، فلا يرى أي صف (Fail-closed) |
| سلسلة فارغة `''` | قبل 0018 كان الاستعلام ينهار بخطأ `''::uuid`؛ بعدها يعيد `NULLIF` القيمة `NULL` فيرفض الوصول بلا انهيار |

تكتشف `0018` السياسات وقت التشغيل من `pg_policies` (`policyname = 'tenant_isolation'`) بدل الاعتماد على قائمة ثابتة.

### كيف يصل المستأجر إلى قاعدة البيانات (GUCs)

1. يضبط `RequestContextMiddleware` (`app/api/middleware/request_context.py`) قيمة `ContextVar` المستأجر من ترويسة `X-Tenant-ID` إن وُجدت، وقيمة المستخدم بـ `None`.
2. يربط `_authenticate` مستأجر JWT قبل استعلام المستخدم ويتحقق من مطابقته للمستخدم
   المحفوظ. التوكن القديم بلا `tid` يستخدم المنصة لتحميل الهوية فقط، ثم يضيّق سياق المستأجر
   وGUC في **المعاملة الحالية** إلى مستأجر المستخدم. يعيد `get_current_user` غير المتزامن
   ربط المستأجر والمستخدم في سياق مهمة الطلب؛ الاعتماديات المتزامنة تعمل في سياق منسوخ.
   هذه هي الآلية القائمة، وليست إضافة async ضمن المراجعة الحالية. ترويسة العميل لا تثبت هويته.
3. يضبط المستمع `after_begin` على `Session` (`app/db/session.py`) في بداية **كل معاملة**:

```sql
SELECT set_config('app.current_tenant',  :tenant, true);  -- is_local = true ≡ SET LOCAL
SELECT set_config('app.current_user_id', :user,   true);  -- '' عند غياب المستخدم
```

`is_local = true` يحصر القيمة في المعاملة، فتُمحى عند `COMMIT`/`ROLLBACK` ولا تتسرب إلى طلب آخر يعيد استخدام الاتصال نفسه من الـ Pool (يتحقق من ذلك `test_set_local_does_not_leak_across_transactions`). ولا يعمل المستمع إلا مع PostgreSQL، ويتجاهل SQLite.

4. خارج الطلبات (Workers والسكربتات) يربط `session_scope(tenant_id)` المستأجر في `ContextVar` طوال النطاق ثم يعيده إلى حاله.

### المخاطر والقيود المعروفة

> **⚠ Fail-open عند غياب المستأجر.** إذا لم يُربط أي مستأجر، يطبّق المستمع **المستأجر المنصّة** (`get_current_tenant() or PLATFORM_TENANT_ID`)، فتُفتح كل الصفوف بدل أن تُغلق. هذا مقصود لمسارات مثل login وrefresh وhealth، لكنه يعني أن أي مسار أو Worker ينسى ربط المستأجر يعمل بصلاحيات المنصّة. ويُضاف إليه أن الطلبات غير الموثّقة تستطيع اختيار المستأجر عبر ترويسة `X-Tenant-ID`، بما فيها قيمة nil-UUID.

> **⚠ المستخدمون الخارقون (Superusers) وأدوار `BYPASSRLS` يتجاوزون RLS حتى مع `FORCE`.** `FORCE` لا يُخضع للسياسة إلا **مالك الجدول**. لذا يجب أن يتصل التطبيق بدور لا يملك `SUPERUSER` ولا `BYPASSRLS`. ينشئ CI الدور:
>
> ```sql
> CREATE ROLE mesaar_app LOGIN PASSWORD 'mesaar_app'
>   NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
> GRANT USAGE, CREATE ON SCHEMA public TO mesaar_app;
> ```

> **دور Compose:** يبقى `mesaar` حساب إدارة Superuser، لكن الخدمات تتصل الآن بـ`mesaar_app`
> غير الخارق الذي يهيئه `docker/postgres/init-app-role.sql`. Volumes القائمة تحتاج تشغيل
> السكربت يدويًا؛ الصلاحيات لا تنقل ملكية الجداول. راجع [التشغيل](operations.md).

### العزل في طبقة التطبيق

- المستودعات (`app/repositories/base.py`) **لا تضيف مرشّح `tenant_id`**، وتعتمد كليًا على RLS. يستثنى من ذلك `event_store_repository` و`projection_repository` اللذان يرشّحان صراحةً في استعلامات الإعادة (Replay) والحذف.
- بعض الخدمات تتحقق صراحةً من `obj.tenant_id` للمعرّفات الأجنبية التي يرسلها العميل، كدفاع ثانٍ (Defense-in-depth):
  - `_owned(...)` في `billing_service` و`claims_service` و`settlement_service` و`integration_service`.
  - `_require_tenant_owned(...)` في `compliance_service` و`equipment_service` و`shipment_service`.
- يتحقق `order_service` الآن أيضًا من مطابقة `customer.tenant_id`. رُفض السائق المحذوف/غير
  النشط وأضيف التحقق من ملكية السائق في القبول الذاتي. لا تغني هذه الحراس عن RLS أو
  مراجعة ملكية كل مورد.

---

## 4. خريطة الجداول حسب المجال

### الهوية والتشغيل الأساسي (`0001`–`0004`)

| الجدول | الغرض |
|---|---|
| `tenants` | المنظمات المستأجرة + المستأجر المنصّة |
| `users` | المستخدمون ودورهم الوحيد (`role`) وكلمة المرور المجزّأة |
| `drivers` | ملف السائق (رخصة، هاتف، توفّر)، علاقة 1:1 مع `users` |
| `vehicles` | المركبات وسعتها وحالتها |
| `warehouses` | المستودعات وموقعها وسعتها |
| `shipments` | الشحنة: المسار، الإسناد (سائق/مركبة/معدة)، دورة الحياة، السعر |
| `shipment_tracking_events` | سجل تتبع ملحق فقط (Append-only): حالة، موقع، إثبات تسليم |

### العملاء والطلبات (`0006`–`0007`)

| الجدول | الغرض |
|---|---|
| `customers` | العميل التجاري: الهوية القانونية والضريبية، المخاطر، الائتمان |
| `orders` | طلب النقل الصادر من العميل، وقد تنتج عنه شحنة أو أكثر |

### المعدات والأصول (`0009`)

| الجدول | الغرض |
|---|---|
| `equipment_categories` | تصنيف هرمي (`parent_id`) للمعدات |
| `equipment_models` | طرازات المعدات ضمن تصنيف |
| `equipment` | الأصل الفعلي: الأبعاد والوزن ومتطلبات التصاريح والمرافقة وموقعه الحالي |

### الامتثال والتصاريح (`0010`)

| الجدول | الغرض |
|---|---|
| `permits` | تصاريح الحمولات الثقيلة أو الاستثنائية لشحنة أو معدة أو مركبة |
| `escorts` | المرافقة (خاصة أو شرطية) المرتبطة بشحنة أو تصريح |
| `route_restrictions` | قيود الطرق حسب المنطقة والنوع |
| `axle_weight_profiles` | توزيع الأحمال على المحاور والتحقق من المطابقة |
| `compliance_checks` | فحوص امتثال، وقد تكون حاجبة (`blocking`) للإرسال |
| `operator_certifications` | شهادات المشغّلين لكل تصنيف معدات |

### التأمين والمطالبات (`0011`)

| الجدول | الغرض |
|---|---|
| `insurance_policies` | وثائق التأمين ونطاق تغطيتها |
| `coverage_rules` | قواعد التغطية لكل وثيقة |
| `claims` | المطالبات المرتبطة بشحنة أو طلب أو عميل أو معدة أو تصريح |
| `damage_reports` | تقارير الضرر التابعة لمطالبة |
| `liability_records` | توزيع المسؤولية على الأطراف |

### الفوترة والتسويات (`0012`)

| الجدول | الغرض |
|---|---|
| `quotes` | عروض الأسعار |
| `invoices` | الفواتير والإشعارات الدائنة (`is_credit_note`) |
| `invoice_lines` | بنود الفاتورة |
| `payments` | المدفوعات على فاتورة |
| `settlements` | تسويات المطالبات والاسترداد ومستحقات الناقلين |
| `payouts` | دفعات صرف التسوية |
| `penalties` | الغرامات على الطلب أو الشحنة أو الفاتورة |

### الإشعارات (`0013`)

| الجدول | الغرض |
|---|---|
| `notification_templates` | قوالب الإشعار لكل قناة ونوع حدث |
| `notifications` | الإشعار الفعلي لمستلم، مع `idempotency_key` |
| `notification_delivery_attempts` | محاولات الإرسال |

### التكاملات الخارجية (`0016`–`0017`)

| الجدول | الغرض |
|---|---|
| `integration_partners` | الشركاء الخارجيون |
| `partner_api_keys` | مفاتيح API للشريك (البادئة فريدة لكل مستأجر) |
| `webhook_subscriptions` | اشتراكات Webhook (السر مشفّر + `encryption_provider`/`encryption_key_id`) |
| `webhook_deliveries` | تسليمات Webhook الصادرة وحالة إعادة المحاولة |
| `webhook_delivery_attempts` | كل محاولة تسليم |
| `inbound_integration_events` | الأحداث الواردة من الشركاء مع منع التكرار (De-dup) |

جداول العمود الفقري للأحداث في القسم 5، وجداول القراءة في القسم 6.

### العلاقات المهمة وسلوك `ON DELETE`

- `tenant_id → tenants.id`: **RESTRICT** في كل الجداول، فلا يُحذف مستأجر له بيانات.
- `drivers.user_id → users`: **CASCADE**، أي أن حذف المستخدم فعليًا يحذف ملف السائق. وكذلك `operator_certifications.user_id`.
- `shipments.client_id → users`: **RESTRICT**. لاحظ أن عميل الشحنة **مستخدم** (`users`)، أما عميل الطلب فهو `customers`.
- `shipments.origin_warehouse_id` و`destination_warehouse_id` إلى `warehouses`: **RESTRICT**.
- `shipments.driver_id` و`vehicle_id` و`equipment_id` و`order_id`: **SET NULL**.
- `orders.customer_id → customers`: **RESTRICT**، و`orders.assigned_dispatcher_id → users`: **SET NULL**.
- `shipment_tracking_events.shipment_id`: **CASCADE**.
- **CASCADE** في علاقات الأب والابن: `invoice_lines`/`payments` إلى `invoices`، و`payouts` إلى `settlements`، و`damage_reports`/`liability_records` إلى `claims`، و`coverage_rules` إلى `insurance_policies`، و`notification_delivery_attempts` إلى `notifications`، وجداول التكامل إلى `integration_partners`/`webhook_subscriptions`/`webhook_deliveries`/`partner_api_keys`، و`proj_ar_aging.customer_id` إلى `customers`.
- `equipment.category_id` و`equipment_models.category_id`: **RESTRICT**. أما بقية الإحالات بين المجالات (permits/claims/invoices/settlements إلى shipments/equipment/orders/customers) فهي **SET NULL** لحفظ السجل التاريخي.

بما أن التطبيق يعتمد الحذف المنطقي، فإن قواعد CASCADE وSET NULL لا تُفعَّل إلا عند حذف فعلي (Hard Delete).

### القيود الفريدة لكل مستأجر (Per-tenant Unique)

استبدلت `0003` القيود الفريدة أحادية العمود بقيود مركّبة تبدأ بـ `tenant_id`:

| الجدول | الأعمدة |
|---|---|
| `users` | `(tenant_id, email)`، والفهرس `ix_users_email` أصبح غير فريد |
| `drivers` | `(tenant_id, user_id)`, `(tenant_id, license_number)` |
| `vehicles` | `(tenant_id, plate_number)`, `(tenant_id, vin)` |
| `warehouses` | `(tenant_id, code)` |
| `shipments` | `(tenant_id, reference_code)` |
| `customers` | `(tenant_id, code)`, `(tenant_id, commercial_registration)`, `(tenant_id, vat_number)` |
| `orders` | `(tenant_id, order_number)` |
| `equipment*` | `(tenant_id, code)` للتصنيفات والطرازات؛ `(tenant_id, equipment_code)`, `(tenant_id, asset_tag)` + فهرس جزئي فريد للرقم التسلسلي |
| `permits` / `claims` / `insurance_policies` | `permit_number` / `claim_number` / `policy_number` |
| `quotes` / `invoices` / `settlements` | `quote_number` / `invoice_number` / `settlement_number` |
| `notification_templates` / `notifications` | `template_code` / `idempotency_key` |
| `integration_partners` / `partner_api_keys` | `name` / `key_prefix` |
| `webhook_subscriptions` | `(tenant_id, partner_id, name)` |
| `webhook_deliveries` | `(tenant_id, subscription_id, source_event_id)`، وهو مفتاح Idempotency |
| `inbound_integration_events` | `(tenant_id, api_key_id, idempotency_key)` |
| `webhook_delivery_attempts` | `(delivery_id, attempt_number)` |

### مخطط العلاقات الأساسية (Core ERD)

يحمل كل كيان أدناه `tenant_id → tenants`، ولم تُرسم كل هذه الأسهم تجنبًا للازدحام.

```mermaid
erDiagram
    tenants ||--o{ users : "tenant_id RESTRICT"
    tenants ||--o{ customers : "tenant_id RESTRICT"
    users ||--o| drivers : "user_id CASCADE"
    warehouses |o--o{ drivers : "home_warehouse_id SET NULL"
    warehouses |o--o{ vehicles : "home_warehouse_id SET NULL"
    warehouses |o--o{ equipment : "current_warehouse_id SET NULL"
    customers ||--o{ orders : "customer_id RESTRICT"
    users |o--o{ orders : "assigned_dispatcher_id SET NULL"
    users ||--o{ shipments : "client_id RESTRICT"
    orders |o--o{ shipments : "order_id SET NULL"
    warehouses ||--o{ shipments : "origin/destination RESTRICT"
    drivers |o--o{ shipments : "driver_id SET NULL"
    vehicles |o--o{ shipments : "vehicle_id SET NULL"
    equipment |o--o{ shipments : "equipment_id SET NULL"
    shipments ||--o{ shipment_tracking_events : "shipment_id CASCADE"
    users |o--o{ shipment_tracking_events : "recorded_by_user_id SET NULL"
    shipments |o--o{ permits : "shipment_id SET NULL"
    equipment |o--o{ permits : "equipment_id SET NULL"
    vehicles |o--o{ permits : "vehicle_id SET NULL"
    shipments |o--o{ claims : "shipment_id SET NULL"
    orders |o--o{ claims : "order_id SET NULL"
    customers |o--o{ claims : "customer_id SET NULL"
    equipment |o--o{ claims : "equipment_id SET NULL"
    permits |o--o{ claims : "permit_id SET NULL"
    customers |o--o{ invoices : "customer_id SET NULL"
    orders |o--o{ invoices : "order_id SET NULL"
    shipments |o--o{ invoices : "shipment_id SET NULL"
    claims |o--o{ invoices : "claim_id SET NULL"
```

---

## 5. العمود الفقري للأحداث (Event Store & Outbox)

أُنشئت هذه الجداول في الترحيلة `0005` (`app/models/event_store.py` و`app/models/audit_log.py`).

### `event_store`: سجل الأحداث وصندوق الصادر (Transactional Outbox)

| العمود | الوصف |
|---|---|
| `event_id` (PK, UUIDv7) | المعرّف ومفتاح Idempotency بين الأنظمة |
| `tenant_id` | FK RESTRICT، يخضع لـ RLS |
| `aggregate_type`, `aggregate_id`, `aggregate_version` (BigInteger) | هوية التجميع وترتيبه |
| `event_type`, `event_version` | نوع الحدث وإصدار مخططه |
| `payload` (JSONB, NOT NULL), `metadata` (JSONB) | يُربط `metadata` في Python باسم `event_metadata` لأن الاسم محجوز في SQLAlchemy |
| `correlation_id`, `causation_id`, `user_id` | التتبّع والإسناد |
| `occurred_at` / `recorded_at` | وقت وقوع الحدث تجاريًا / وقت تسجيله |
| `published_at`, `publish_attempts`, `last_error`, `next_attempt_at` | أعمدة الـ Outbox: يكون الحدث غير منشور ما دام `published_at IS NULL` |

القيود والفهارس:
- `uq_event_store_aggregate_id_aggregate_version`: يضمن الترتيب لكل تجميع والتزامن التفاؤلي على مستوى الأحداث، فإذا تسابق كاتبان على الإصدار نفسه فشل أحدهما.
- `ix_event_store_unpublished (next_attempt_at) WHERE published_at IS NULL`: فهرس جزئي يستطلع منه الـ Relay الأحداث غير المنشورة.
- `ix_event_store_tenant_id_occurred_at` و`ix_event_store_aggregate (aggregate_type, aggregate_id, aggregate_version)` و`ix_event_store_tenant_id_event_type`: لإعادة التشغيل (Replay).
- الجدول غير مجزّأ (Non-partitioned) عمدًا، لأن القيد الفريد العام لا يتوافق مع التجزئة حسب `occurred_at`.

الكتابة تتم في معاملة الأعمال نفسها (القسم 9)، ويُنشر الحدث لاحقًا عبر الـ Outbox Relay.

### الجداول المساندة

| الجدول | RLS | الغرض والأعمدة |
|---|---|---|
| `processed_events` | لا | سجل Idempotency للمستهلكين: PK `(consumer, event_id)` + `processed_at`. وجود الصف يعني أن المستهلك عالج الحدث |
| `dead_letter_events` | نعم | الأحداث التي استنفدت المحاولات: `event_id` (مفهرس)، `consumer`، `event_type`، `payload`، `failure_reason`، `retry_count`، `first_failed_at`/`last_failed_at`، `replayed_at`. فهرس `(tenant_id, last_failed_at)` |
| `outbox_relay_state` | لا | مؤشر الـ Relay ونبضه: `relay_name` (فريد)، `last_published_at`، `last_run_at`، `published_count`، لمراقبة تأخر الـ Outbox |
| `audit_log` | نعم | سجل تدقيق غير قابل للتعديل: `table_name`، `row_id`، `action ∈ {I,U,D,E}` (`ck_audit_log_action`)، `old_row`/`new_row` (JSONB)، `actor_user_id`، `event_id` (لصفوف `E` المرتبطة بحدث)، `txid`، `at`. فهرس `(tenant_id, table_name, row_id, at)` |

ملاحظة: تذكر الترحيلة `0005` أن صلاحيات الإلحاق فقط (`INSERT`/`SELECT`) على هذه الجداول تتطلب دورًا مخصّصًا غير superuser، وأنها **لم تُطبَّق** في أي ترحيلة حتى الآن.

---

## 6. جداول القراءة (Projections)

أُنشئت في `0014` وعُزّزت في `0015` (`app/models/projection.py`)، وهي نماذج قراءة وفق CQRS (ADR-006):

| الجدول | المفتاح الفريد | المحتوى |
|---|---|---|
| `proj_shipment_performance` | `(tenant_id, period_date)` | أداء الشحن اليومي ومتوسط مدة التسليم |
| `proj_financial_summary` | `(tenant_id, period_date, currency)` | الملخص المالي |
| `proj_ar_aging` | `(tenant_id, customer_id, currency)` | أعمار الذمم المدينة لكل عميل |
| `proj_claims_metrics` | `(tenant_id, period_date, currency)` | مؤشرات المطالبات ودورة إغلاقها |
| `proj_compliance_metrics` | `(tenant_id, period_date)` | مؤشرات الامتثال |
| `proj_notification_deliverability` | `(tenant_id, period_date)` | معدلات تسليم الإشعارات |
| `proj_operations_dashboard` | `(tenant_id)` | لقطة واحدة للوحة العمليات لكل مستأجر |
| `projection_health` | `(tenant_id, projection_name)` | صحة كل إسقاط: `last_event_id`، `events_applied`، `status`، `last_rebuilt_at`، `rebuild_count`، ... |

الخصائص:
- **ليست مصدر الحقيقة**: يمكن حذفها وإعادة بنائها بالكامل من `event_store` (`ProjectionService.rebuild_all_projections` و`rebuild_projection`، بترتيب `occurred_at, aggregate_version, event_id` لكل مستأجر).
- لا SoftDelete ولا `version`، وتخضع لـ RLS.
- أضافت `0015` أعمدة عدّ داخلية للمتوسطات التراكمية وأعمدة أتمتة الصحة، كلها `NOT NULL` مع `server_default`.

---

## 7. الترحيلات (Migrations)

| # | الملف | الغرض |
|---|---|---|
| 0001 | `0001_baseline.py` | الجداول الأساسية: users, warehouses, drivers, vehicles, shipments, shipment_tracking_events + فهرس `(shipment_id, event_time)` |
| 0002 | `0002_shipment_offer_fields.py` | `cargo_type`, `price_sar`, `required_vehicle_type` في shipments |
| 0003 | `0003_multi_tenancy_rls.py` | `tenants` + المستأجر المنصّة، و`tenant_id` (nullable ثم ملء ثم NOT NULL ثم FK ثم فهرس)، والقيود الفريدة لكل مستأجر، وRLS للجداول الستة |
| 0004 | `0004_lifecycle_audit_columns.py` | `version`، `created_by`/`updated_by`، `deleted_at`، `shipments.currency_code` + CHECK |
| 0005 | `0005_event_backbone.py` | event_store, processed_events, dead_letter_events, outbox_relay_state, audit_log + RLS |
| 0006 | `0006_customer_domain.py` | customers |
| 0007 | `0007_order_domain.py` | orders |
| 0008 | `0008_shipment_domain.py` | أعمدة shipments الإضافية (`order_id`، `priority`، `equipment_id`، ...)، وفهارس التشغيل، والفهارس الجزئية |
| 0009 | `0009_equipment_domain.py` | equipment_categories, equipment_models, equipment + FK `shipments.equipment_id` |
| 0010 | `0010_compliance_permits_domain.py` | جداول الامتثال الستة |
| 0011 | `0011_insurance_claims_domain.py` | جداول التأمين الخمسة |
| 0012 | `0012_billing_settlements_domain.py` | جداول الفوترة السبعة |
| 0013 | `0013_notifications_communications_domain.py` | جداول الإشعارات + توسيع `alembic_version.version_num` إلى `VARCHAR(128)` |
| 0014 | `0014_reporting_analytics_projections_domain.py` | جداول `proj_*` + `projection_health` |
| 0015 | `0015_event_enrichment_analytics_hardening.py` | أعمدة العدّ والصحة في الإسقاطات |
| 0016 | `0016_external_integrations_webhooks_domain.py` | جداول التكامل الستة |
| 0017 | `0017_integration_delivery_worker_hardening.py` | بيانات تشفير السر في `webhook_subscriptions` + فهرس `(status, next_attempt_at)` |
| 0018 | `0018_rls_policy_nullif_fail_closed.py` | إعادة إنشاء كل سياسات `tenant_isolation` مع `NULLIF` (بلا تغيير في المخطط) |
| 0019 | `0019_shipments_equipment_id_index.py` | `ix_shipments_equipment_id` (`if_not_exists=True`) |

### القواعد

1. **سلسلة خطية**: لكل ترحيلة `down_revision` واحد، والمعرّفات نصية وصفية (`0019_shipments_equipment_id_index`).
2. **لا تُعدَّل ترحيلة طُبّقت**، بل تُضاف مراجعة جديدة. مثال ذلك `0018` التي صححت السياسات بدل تعديل `0003` وما بعدها، و`0019` التي أضافت فهرسًا ناقصًا.
3. العمليات الخاصة بـ PostgreSQL (RLS، والفهارس الجزئية، وبعض الـ FKs، وقيود Regex) محمية بشرط `_is_postgres()`.
4. يجب أن يبقى النموذج والترحيلة متطابقين حرفيًا، بما في ذلك أسماء الفهارس و`server_default` وأطوال الأعمدة.

### الأوامر

```bash
alembic upgrade head                                   # أو: make migrate
alembic revision --autogenerate -m "describe change"   # أو: make revision MSG="describe change"
alembic check                                          # يفشل إذا اختلفت النماذج عن الترحيلات
alembic upgrade head --sql                             # توليد SQL دون اتصال (Offline)
```

- يقرأ `migrations/env.py` عنوان الاتصال من `get_settings().database_url` (متغير البيئة `DATABASE_URL`) ويتجاهل `sqlalchemy.url` في `alembic.ini`، ويستخدم `target_metadata = Base.metadata` مع `compare_type=True` و`compare_server_default=True`. استيراد أي وحدة من `app.models` يحمّل الحزمة كاملة، فتُسجَّل كل النماذج.
- `alembic.ini` يشغّل خطاف ما بعد الكتابة (Post-write Hook) `black -l 100` على كل ملف ترحيلة جديد.
- مخرجات `--autogenerate` نقطة بداية فقط، ويجب مراجعتها يدويًا لأن RLS والفهارس الجزئية لا تُكتشف تلقائيًا.

### كشف الانحراف (Drift Detection)

يشغّل CI الخطوة `alembic upgrade head && alembic check` قبل `pytest`. تتضمن الحالة القائمة
فهارس `0001/0008/0009/0016` وقيم `server_default` المطابقة للنماذج، وطول `claims.severity`
البالغ16، وترحيل `0019` لفهرس المعدات. كانت هذه التهيئة والترحيلات موجودة قبل مراجعة
التنظيف الحالية؛ لم تُنشأ ضمنها. يمنع الفحص اقتراح حذف فهارس أو قيم افتراضية يعتمد عليها الإنتاج.

---

## 8. الفهارس المهمة

### الفهارس الجزئية (Partial Indexes)، في PostgreSQL فقط

| الفهرس | التعريف | الاستخدام |
|---|---|---|
| `ix_shipments_ready_unassigned` | `(tenant_id) WHERE status = 'READY' AND driver_id IS NULL` | عروض الشحن المتاحة للسائقين |
| `ix_shipments_active_driver` | `(driver_id) WHERE status IN ('ASSIGNED','PICKED_UP','IN_TRANSIT','DELAYED') AND deleted_at IS NULL` | فحص الإسناد النشط للسائق |
| `ix_shipments_active_vehicle` | `(vehicle_id)` بالشرط نفسه | فحص الإسناد النشط للمركبة |
| `uq_equipment_tenant_id_serial_number` | `UNIQUE (tenant_id, serial_number) WHERE serial_number IS NOT NULL AND deleted_at IS NULL` | تفرّد الرقم التسلسلي للمعدات الحية فقط |
| `ix_event_store_unpublished` | `(next_attempt_at) WHERE published_at IS NULL` | استطلاع الـ Outbox |

ملاحظة: الفهرسان `ix_shipments_active_*` **غير فريدين** (Non-unique)، فهما يسرّعان فحص الحصرية في الخدمة ولا يفرضانه على مستوى قاعدة البيانات.

### الفهارس المركّبة (Composite)

- `ix_shipment_tracking_events_shipment_id_event_time (shipment_id, event_time)`: لقراءة السجل مرتبًا ولحماية رتابة `event_time`.
- `ix_webhook_deliveries_status_next_attempt_at (status, next_attempt_at)`: لمسح إعادة المحاولة في عامل التسليم (`0017`).
- `ix_audit_log_tenant_table_row_at` و`ix_dead_letter_events_tenant_id_last_failed_at` وفهارس `event_store` (القسم 5).
- كل قيد `UNIQUE (tenant_id, ...)` يعمل أيضًا كفهرس يبدأ بـ `tenant_id`.

بالإضافة إلى ذلك يوجد فهرس على `tenant_id` في كل جدول (عدا الجداول الثلاثة المذكورة في القسم 2)، وعلى أعمدة `status` و`priority` ومعظم المفاتيح الأجنبية.

### فجوات معروفة: مفاتيح أجنبية بلا فهرس

جرى التحقق من كل عمود في القائمة التالية مقابل النموذج والترحيلات، ولا يوجد له أي فهرس:

| العمود | الأثر |
|---|---|
| `shipments.client_id` | قوائم شحنات العميل، وفحص `RESTRICT` عند حذف مستخدم |
| `shipments.origin_warehouse_id`, `shipments.destination_warehouse_id` | استعلامات المستودع، وفحص `RESTRICT` عند حذف مستودع |
| `claims.customer_id`, `claims.order_id` | مطالبات العميل أو الطلب، و`SET NULL` عند الحذف |
| `settlements.customer_id`, `settlements.shipment_id` | كما سبق |
| `invoices.quote_id` | ربط الفاتورة بعرض السعر |
| `notifications.template_id` | `SET NULL` عند حذف قالب |
| `drivers.phone_number` | ليس مفتاحًا أجنبيًا، لكنه مفتاح البحث في تسجيل الدخول بالهاتف (`DriverRepository.get_by_phone`)، وهو بلا فهرس ولا قيد تفرّد |

ومن الفجوات الأخرى المؤكدة: `permits.vehicle_id`، و`axle_weight_profiles.vehicle_id`، و`compliance_checks.equipment_id/vehicle_id/permit_id`، و`claims.compliance_check_id/permit_id`، و`damage_reports.shipment_id/equipment_id`، و`settlements.equipment_id`، و`drivers.home_warehouse_id`، و`vehicles.home_warehouse_id`، و`shipment_tracking_events.recorded_by_user_id`. أي فهرس جديد يُضاف **بترحيلة جديدة** وتعديل مطابق في النموذج، وإلا فشل `alembic check`.

---

## 9. إدارة الجلسات والمعاملات (Sessions & Transactions)

### المحرك والمصنع (`app/db/session.py`)

```python
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False,
                            expire_on_commit=False, future=True)
```

- `expire_on_commit=False`: تبقى الكائنات قابلة للقراءة بعد `commit()`، وهذا ضروري لتسلسل الاستجابة (Serialization) بعد إنهاء المعاملة.
- `autoflush=False`: على الخدمات استدعاء `flush()` صراحةً عند الحاجة إلى معرّفات أو قيود قبل الالتزام.
- `pool_pre_ping=True`. إعدادات الـ Pool تُقرأ من البيئة ولا تُطبَّق على SQLite:

| متغير البيئة | الافتراضي |
|---|---|
| `DATABASE_URL` | `postgresql+psycopg2://postgres:postgres@localhost:5432/logistics` |
| `DB_POOL_SIZE` | 5 |
| `DB_MAX_OVERFLOW` | 10 |
| `DB_POOL_TIMEOUT` | 30 ثانية |
| `DB_POOL_RECYCLE_SECONDS` | 1800 |
| `DB_ECHO` | `false` |

### نقاط الدخول

- **`get_session()`**: اعتمادية FastAPI تعطي جلسة وتغلقها في `finally`، **دون Commit أو Rollback تلقائي**، فإدارة المعاملة مسؤولية الخدمة.
- **`session_scope(tenant_id=None)`**: للـ Workers والسكربتات. يلتزم عند النجاح، ويتراجع عند أي استثناء (سواء من قاعدة البيانات أو غيرها)، ويغلق الجلسة دائمًا، ويربط المستأجر ثم يعيده إلى حاله.

### وحدة العمل في الخدمات (Unit of Work)

النمط الحالي في خدمات المجالات (customer، order، shipment، equipment، compliance، claims، billing، ...):

```text
validate → repo.create/update → session.flush()        # يُسند المعرّفات ويفحص القيود
        → EventStoreRepository.append(envelope)        # صف الحدث + صف التدقيق
        → session.commit()                             # التزام واحد: التغيير والحدث معًا
```

بهذا يُكتب التغيير وحدثه في معاملة واحدة (Transactional Outbox)، فلا يوجد تغيير بلا حدث ولا حدث بلا تغيير.

### عدم اتساق معروف

المستودعات القديمة `user_repository` و`driver_repository` و`vehicle_repository` و`warehouse_repository` و`tracking_event_repository` **تستدعي `commit()` داخل المستودع** في `create`/`update`/`delete`. لذلك لا يمكن ضمّ هذه العمليات إلى وحدة عمل أكبر ولا إلحاق حدث بها في المعاملة نفسها، ويفصل الالتزام المبكر الـ GUC عن العمليات اللاحقة لأنها تبدأ معاملة جديدة (يعيد المستمع ضبطه، فلا خطر أمني في ذلك، لكنه يكسر الذرية Atomicity). أما المستودعات المبنية على `app/repositories/base.py` فلا تلتزم.

---

## 10. اختبارات قاعدة البيانات

### المجموعة الأساسية: SQLite في الذاكرة

- تُبنى المخططات بـ `Base.metadata.create_all()` من النماذج مباشرة، لا من الترحيلات.
- يسجّل `tests/conftest.py` قاعدتي ترجمة (`@compiles`) لـ SQLite:
  - `JSONB` يُترجم إلى `JSON`.
  - قيود `CHECK` التي تحتوي معامل Regex الخاص بـ PostgreSQL (`~`)، مثل `currency_code` والبريد، **تُتجاهل**.
- `tests/sqlite_support.py` يوفّر `make_sqlite_engine(models)` (مع `StaticPool` حتى يرى خيط `TestClient` القاعدة نفسها، ويبني جداول النماذج المطلوبة فقط) و`seed_tenant_user(...)`.
- `tests/*_sqlite.py` (`billing`، `compliance`، `equipment`، `insurance`، `integrations`، `notifications`، `reporting`، `shipment`) أدوات تهيئة لكل مجال.
- في SQLite لا يوجد RLS، والمستمع `after_begin` لا يفعل شيئًا، والفهارس الجزئية تُبنى بلا شروط (عدا `uq_equipment_tenant_id_serial_number` الذي يعرّف `sqlite_where`). **لذلك لا تثبت هذه المجموعة شيئًا عن العزل.**
- `tests/test_session_guc.py` يختبر المستمع باتصال وهمي (Fake Connection): يتحقق من ضبط GUCs، ومن الرجوع إلى المستأجر المنصّة ومستخدم فارغ، ومن عدم عمله خارج PostgreSQL.
- `tests/test_migrations_postgresql.py` يولّد SQL الترحيلات دون اتصال حتى `0017` بلهجة PostgreSQL، ويتحقق من حد 63 حرفًا لأسماء القيود ومن توسيع `alembic_version`. لا يحتاج إلى قاعدة بيانات. يتوقف عند `0017` لأن `0018` تستعلم `pg_policies` وقت التشغيل.

### اختبارات PostgreSQL المشروطة

| الملف | شرط التفعيل | ما يثبته |
|---|---|---|
| `tests/test_tenant_isolation_pg.py` | `TEST_DATABASE_URL` | كل مستأجر يرى صفوفه فقط؛ غياب GUC أو تفريغه لا يُظهر صفوفًا ولا يسبب انهيارًا؛ المنصّة ترى الكل؛ `SET LOCAL` لا يتسرب بين المعاملات |
| `tests/test_event_backbone_pg.py` | `DATABASE_URL` يبدأ بـ `postgres` | الإلحاق مع التدقيق، تعارض التزامن، نشر الـ Relay مرة واحدة، ترتيب الـ Replay، RLS على `event_store`، الـ DLQ، إعادة بناء الإسقاطات |

**يجب أن يشير العنوان إلى دور ليس superuser**، وإلا تجاوز الاتصال RLS وفقد الاختبار معنى
إثبات العزل. ينفذ اختبار العزل عمليات `drop_all/create_all`؛ استخدم قاعدة اختبار مؤقتة
منفصلة عن بيانات التطوير والإنتاج.

### التشغيل محليًا

```bash
# 1) المجموعة الكاملة (SQLite) — تتخطى اختبارات PG تلقائيًا
pytest -q                                   # أو: make test

# 2) جهّز قاعدة اختبار مؤقتة منفصلة ودورًا غير خارق وفق development.md

# 3) ترحيل + كشف الانحراف + اختبارات PG بالدور غير الخارق
export DATABASE_URL=postgresql+psycopg2://mesaar_test_app:mesaar_test_app@localhost:55432/mesaar_test
export TEST_DATABASE_URL=$DATABASE_URL
alembic upgrade head && alembic check
pytest -q tests/test_tenant_isolation_pg.py tests/test_event_backbone_pg.py
```

في CI (`.github/workflows/ci.yml`) ينشأ الدور `mesaar_app`، ثم تنفذ فحوص Ruff وBlack وMypy
الإلزامية، ثم الترحيلات وفحص الانحراف وPytest. تضبط متغيرات قاعدة الاختبار على الدور غير الخارق.
