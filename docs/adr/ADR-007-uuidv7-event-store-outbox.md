# ADR-007 — UUIDv7 وسجل الأحداث الموحد و Transactional Outbox

- **الحالة:** Accepted في 2026-06-20؛ تعديل خطة الترحيل والتراجع 2026-06-22 (المرحلة 6.5).
- **التاريخ:** 2026-06-20؛ صاحب القرار: قائد البرنامج.
- **يبني على:** ADR-002 و ADR-004 و ADR-006.

## السياق

قدمت المرحلة 3 مفاتيح UUID وتوصية UUIDv7، وصممت المرحلة 4 تدفق CQRS-lite. يحسم هذا القرار
توليد المعرّفات وملكية السجل ونشر الحدث دون سباق Dual-write.

## القرار

1. **UUIDv7 وفق RFC9562**، مولد داخل التطبيق عبر`app.db.uuidv7.uuid7` و`BaseModel`، للجداول
   الجديدة كثيرة الإدراج:`event_store` و`shipment_tracking_events` و`audit_log` و
   `ml_predictions` و`proj_*`. تبقى UUIDv4 للجداول المرجعية؛ **لا تحويل للمفاتيح القائمة**.
2. **event_store واحد** إلحاقي لكل Aggregates. يحمل الغلاف event_id (مفتاح Idempotency)،
   tenant_id و aggregate_type/id/version و event_type و payload و occurred_at/recorded_at
   و correlation_id و causation_id و published_at. القيد`UNIQUE(aggregate_id,aggregate_version)`
   للترتيب والتزامن؛ القرار يتضمن Range Partitioning شهريًا حسب occurred_at.
   يبقى shipment_tracking_events شريحة التتبع للمستخدم.
3. **Transactional Outbox:** يكتب التغيير وصف الحدث في معاملة محلية واحدة. Relay مستقل
   ينشر الصفوف غير المنشورة ثم يختم published_at. لا نشر مباشر إلى Broker في مسار الأمر.
   التسليم At-least-once وإزالة التكرار عبر processed_events(consumer,event_id).

## الآثار والبدائل

UUIDv7 يرتب إدراج الفهارس زمنيًا، والسجل الموحد يقلل تكرار إدارة التاريخ والإعادة، و Outbox
يمنع فقد الحدث بين Commit والنشر. يلزم تشغيل Relay ومراقبة التأخر وإدارة الفهارس والأقسام.
رُفض UUIDv4 للجميع و ULID/Bigint وسجل لكل Aggregate والنشر دون Outbox. أُجل Full Event Sourcing؛
يبقى Aggregate مصدر الحالة و Replay للإسقاطات. لا توجد قياسات أداء تثبت نسبة تحسن.

## خطة الترحيل — تعديل 2026-06-22

بعد M1 والعزل، وبلا تحويل UUIDv4 القائمة:

1. إنشاء Event Store و Processed Events والغلاف والقيد والتجزئة والعزل.
2. Shadow Writes داخل معاملة الأعمال خلف`EVENT_STORE_ENABLED`، والـ Relay متوقف؛ مقارنة السجل بالتتبع.
3. Backfill اختياري محدود ومتساوي الأثر للأحداث التاريخية.
4. تفعيل Relay ومستهلك واحد كل مرة ومراقبة التأخر.
5. إعادة بناء الإسقاطات ثم تحويل القراءات.
6. جعل إلحاق الأحداث إلزاميًا وجدولة إدارة الأقسام والاحتفاظ.

الخطة تاريخية؛ **Feature Flag و Backfill وإدارة الأقسام غير منفذة حاليًا**.

## التراجع والتعارض الأصلي

المبدأ: إيقاف النشر/الإلحاق عند الحاجة مع بقاء الحالة التشغيلية، و**عدم حذف أو تغيير تاريخ
ملتزم**. إيقاف Relay يراكم الأحداث ويمكن استئنافه مع منع التكرار.
اشتملت الخطة الأصلية أيضًا على تعطيل Feature Flag، وإسقاط الجداول غير المستخدمة بترحيل عكسي،
و Truncate لإعادة Backfill. تتعارض مقترحات الحذف مع حظر حذف التاريخ، و Feature Flag غير موجود.
لا تنفذها كدليل تشغيل؛ يلزم ADR جديد وخطة حفظ بيانات لحسم التعارض.

## المطابقة الحالية

السجل الموحد و UUIDv7 للأحداث والتدقيق و Outbox و Relay و Idempotency منفذة. التجزئة غير
منفذة؛ يشترط PostgreSQL تضمين مفتاح التقسيم في القيد الفريد، بخلاف القيد العام الحالي.
الإسقاطات تستخدم UUIDv4 ولا ترث BaseModel. هذه فروق مسجلة دون تغيير القرار.
المصادر التاريخية:[تصميم البيانات](../archive/03-database-architecture.md)،
[الأحداث](../archive/04-event-storming-and-state-machines.md)،
[تسوية 6.5](../archive/09a-reconciliation-and-closure.md).
