# دليل استخدام API

**العقد المعتمد** هو المخطط المولَّد من الكود: `GET /openapi.json` (وواجهتا `/docs` و`/redoc`).
يضم حاليًا 183 مسارًا و243 عملية. هذا المستند يشرح القواعد المشتركة فقط؛ قائمة النقاط
لكل مجال في [domains.md](domains.md).

> `api/openapi.yaml` مسودة يدوية متقادمة وليست العقد الحالي؛ تصف مثلًا مسارًا غير موجود
> (`POST /shipments/{id}/status`). الرجوع إليها تاريخي فقط.

## 1. الإصدارات والمسارات

| البادئة | المحتوى |
| --- | --- |
| `/v1` (`API_V1_PREFIX`) | كل واجهات الأعمال (ADR-005) |
| بدون بادئة | `/health`، `/health/live`، `/health/ready`، `/metrics`، `/docs`، `/redoc`، `/openapi.json` |

البادئات تحت `/v1`: `/auth`، `/users`، `/drivers`، `/vehicles`، `/warehouses`، `/shipments`،
`/customers`، `/orders`، `/equipment`، `/compliance`، `/insurance`، `/claims`، `/billing`،
`/notifications`، `/analytics`، `/integrations`، إضافة إلى نقاط الخدمة الذاتية للسائق
(`/auth/driver/login`، `/drivers/me`، `/shipments/nearby`، `/shipments/{id}/accept|decline`).

## 2. المصادقة

### المستخدمون (JWT)

| العملية | الطلب | ملاحظات |
| --- | --- | --- |
| تسجيل مؤسسة جديدة | `POST /v1/auth/register` `{email, password, full_name?, organization_name, tenant_slug}` | ينشئ المستأجر ومستخدمًا بدور `admin` |
| تسجيل الدخول | `POST /v1/auth/login` `{email, password, tenant_slug?}` | أرسل `tenant_slug` دائمًا: البريد فريد داخل المستأجر فقط |
| تجديد التوكن | `POST /v1/auth/refresh` `{refresh_token}` | Refresh Token يُستهلك مرة واحدة ويُستبدل (Rotation) |
| تسجيل الخروج | `POST /v1/auth/logout` `{refresh_token?}` + Bearer | يضيف `jti` إلى قائمة الإلغاء ويلغي Refresh Token |
| المستخدم الحالي | `GET /v1/auth/me` | |

الاستجابة: `{access_token, token_type: "bearer", expires_in, refresh_token, user}`.
أرسل بعدها `Authorization: Bearer <access_token>`.

**المستأجر:** يُستخرج من مطالبة `tid` في التوكن ويُربط بسياق الطلب. ترويسة `X-Tenant-ID`
لا تغيّر مستأجر طلب مصادَق عليه؛ تُستخدم فقط للسجلات والمسارات غير المصادَق عليها.

**السائق:** `POST /v1/auth/driver/login` `{phone, otp?}` — التحقق من OTP غير منفذ (Stub)،
لذلك تعيد النقطة **501** عند `ENVIRONMENT=production`.

### الشركاء (API Keys)

تُدار المفاتيح عبر `/v1/integrations/partners/{id}/api-keys` (JWT لمدير/مسؤول)، ويُعرض المفتاح
النصي مرة واحدة عند الإنشاء. النقطة الواردة الوحيدة:

```http
POST /v1/integrations/inbound/events
Authorization: Bearer <partner_api_key>
X-Logistic-X-Timestamp: <unix seconds>
X-Logistic-X-Signature: sha256=<hex HMAC-SHA256(key=api_key, msg="{timestamp}.{raw_body}")>
Content-Type: application/json

{"idempotency_key": "...", "event_type": "order.updated", "payload": {...}}
```

- النطاق المطلوب: `integrations:inbound:write`؛ وقائمة IP المسموحة للمفتاح تُطبَّق إن وُجدت (403).
- الطابع الزمني إلزامي وضمن ±300 ثانية وإلا 401؛ تجاوز معدل الطلبات 429 مع `Retry-After`.
- التوقيع غير الصحيح **لا يرفض الطلب**: يُحفظ الحدث بحالة `rejected` وتعود 201 مع
  `signature_valid=false` (سلوك حالي موثق في [status.md](status.md)).
- `idempotency_key` يمنع التكرار ضمن مفتاح API نفسه والمستأجر؛ تدوير المفتاح يغير النطاق.

**Webhooks الصادرة** تُرسل بترويسة `X-Logistic-X-Signature: sha256=<HMAC(secret, body)>` (بدون طابع زمني).

## 3. الأدوار والصلاحيات

الأدوار: `admin`، `manager`، `driver`، `client` (التحقق عبر `require_roles` في كل موجّه).

| المجال | قراءة | كتابة | إجراءات ميدانية | استثناءات |
| --- | --- | --- | --- | --- |
| shipments، orders، equipment | الأربعة | admin، manager | admin، manager، driver | — |
| compliance | الأربعة | admin، manager | — | التجاوز (override): admin، manager |
| insurance | الأربعة | admin، manager | — | — |
| claims، billing | الأربعة | admin، manager | — | تجاوزات مالية (فوق المبلغ/إلغاء فاتورة مدفوعة): admin |
| customers | admin، manager، client | admin، manager | — | عمليتان للمسؤول فقط |
| notifications | الأربعة (غير المديرين يرون إشعاراتهم فقط) | admin، manager | — | — |
| analytics | admin، manager | — | — | إعادة بناء الإسقاطات: admin |
| integrations | admin، manager | admin، manager | — | بعض العمليات: admin |
| users | admin، manager (GET) | admin | — | لا توجد نقطة لعرض القائمة |
| drivers، vehicles، warehouses | admin، manager | admin، manager | — | — |

> **قيد معروف:** أدوار `client` و`driver` تقرأ معظم بيانات المستأجر دون فلترة بالملكية،
> و`driver` يمكنه تنفيذ الإجراءات الميدانية على أي شحنة في المستأجر.

## 4. القوائم والترقيم والبحث

نقاط القوائم في المجالات الحديثة تعيد `Page`:

```json
{"items": [...], "total": 42, "page": 1, "size": 50, "pages": 1}
```

| المعامل | القيمة |
| --- | --- |
| `page` | يبدأ من 1 |
| `size` | 1–200 (الافتراضي 50) |
| `q` | بحث نصي حيث يدعمه المجال |
| `sort_by` / `sort_dir` | حقل من قائمة مسموحة لكل مجال / `asc` أو `desc` |
| `include_deleted` | يضمّن الصفوف المحذوفة منطقيًا (Soft Delete) |
| فلاتر | حسب المجال (`status`، `customer_id`، تواريخ...) |

نقاط `drivers` و`vehicles` و`warehouses` القديمة تعيد قائمة عادية (`offset`/`limit`).

## 5. الأخطاء

أخطاء التطبيق والمجال والتحقق تعود بالغلاف الآتي، مع `request_id` المطابق لترويسة
`X-Request-ID`. تبقى استثناءات `HTTPException` بصيغة FastAPI الموضحة بعد الجدول:

```json
{"error": {"code": "invalid_status_transition", "message": "...", "details": null, "request_id": "..."}}
```

| HTTP | `code` | المصدر |
| --- | --- | --- |
| 400 | `domain_error` | `DomainError` عام |
| 401 | — | توكن غير صالح/منتهي/ملغى، مستخدم غير نشط، طابع زمني خارج النافذة |
| 403 | — | الدور غير مسموح، IP غير مسموح، نطاق مفتاح ناقص |
| 404 | `not_found` | الكيان غير موجود (أو ليس ضمن المستأجر) |
| 409 | `conflict`، `capacity_exceeded`، `assignment_conflict`، `invalid_status_transition` | تعارضات الأعمال وآلات الحالات |
| 409 | `concurrency_conflict` | تعديل متزامن (Optimistic Locking أو إصدار Aggregate مكرر) — أعد التحميل ثم حاول |
| 422 | `validation_error`، `invalid_tracking_event` | تحقق المدخلات أو قواعد الأعمال |
| 429 | — | تجاوز معدل الطلبات الواردة للشركاء |
| 500 | `internal_error` | خطأ غير متوقع (يُسجَّل مع Traceback) |
| 501 | — | ميزة غير مفعلة في هذه البيئة (دخول السائق في الإنتاج) |
| 503 | — | `/health/ready` عند تعطل PostgreSQL أو Redis |

الأخطاء 401/403/429/501 الصادرة من `HTTPException` تُعرض بصيغة FastAPI الافتراضية `{"detail": "..."}`.

## 6. قواعد عامة

- كل التواريخ في المدخلات يجب أن تكون timezone-aware (ISO-8601 مع المنطقة)؛ المخرجات بتوقيت UTC.
- رموز العملات ISO-4217 بثلاثة أحرف (تُحوَّل لأحرف كبيرة)؛ المبالغ أرقام عشرية.
- المعرّفات UUID نصية.
- PATCH يحدّث الحقول المرسلة فقط (القيم `null` تُتجاهل).
- الحذف في المجالات الحديثة منطقي (Soft Delete) مع نقطة `restore`.
- انتقالات الحالة تتم عبر نقاط أفعال صريحة (`/submit`، `/approve`، `/pickup`...) لا عبر تعديل `status` مباشرة.
