# مسرد اللغة الموحدة (Ubiquitous Language)

مسرد المصطلحات المعتمدة في الكود وواجهات API والواجهات الرسومية. التعريفات مستخلصة من `app/models/*.py` و`app/models/enums.py` و`app/db/mixins.py` و`app/events/*` و`app/services/*`، وتحل محل [`archive/domain-glossary.md`](./archive/domain-glossary.md).

**اصطلاحات عامة:** جداول بيانات المستأجر تخضع لـRLS، مع استثناءات البنية التحتية في
[قاعدة البيانات](database.md). معظم Enums تخزن القيم الصغيرة عبر `enum_values`؛ تخزن
`users.role` و`vehicles.status` و`shipments.status` وتعدادات التتبع أسماء الأعضاء الكبيرة.
راجع تعريف العمود قبل استخدام قيمة API في SQL يدوي.

## الهوية والمستأجرون

| المصطلح العربي | English term | التعريف | Code identifier |
|---|---|---|---|
| المستأجر | Tenant | حد العزل في المنصة متعددة المستأجرين: منظمة عميلة على المخطط المشترك. له `slug` فريد عالميًا، و`status` (`active`/`suspended`)، و`isolation_mode` (`shared`/`dedicated`)، و`region` تلميحًا لإقامة البيانات. كل كيان آخر يرتبط به عبر `tenant_id`. | `Tenant` / `tenants` |
| مستأجر المنصة | Platform tenant | المستأجر ذو المعرّف الصفري (nil-UUID) «tenant 0»، يُزرع في الترحيل `0003` ويُستخدم للعمليات الإدارية العابرة للمستأجرين. | `PLATFORM_TENANT_ID` (`app.db.tenant`)، `Tenant.is_platform` |
| المستخدم | User | حساب مُصادَق عليه بدور واحد فقط، وله `email` و`hashed_password` و`is_active`. | `User` / `users` |
| الدور | Role | أحد أربعة أدوار: `admin` (مدير النظام)، `manager` (مدير العمليات/الإسناد)، `driver` (السائق)، `client` (العميل). يُفرض عبر `require_roles`. | `UserRole` |
| العميل | Customer | عميل تجاري (منظمة أو فرد) داخل المستأجر، له `code` ونوع (`individual`/`corporate`/`government`/`sme`) وحالة (`active`/`suspended`/`inactive`) و`risk_level` و`credit_status` (`good`/`watch`/`blocked`) وبيانات ضريبية وسجل تجاري. | `Customer` / `customers`، `CustomerType`، `CustomerStatus`، `RiskLevel`، `CreditStatus` |

## الطلبات والشحنات

| المصطلح العربي | English term | التعريف | Code identifier |
|---|---|---|---|
| الطلب | Order | طلب نقل يقدمه عميل، له `order_number` ونوع (`standard`/`express`/`same_day`/`economy`/`return`) ومصدر (`web`/`mobile`/`api`/`phone`/`email`/`walk_in`) وأولوية. دورة حياته: `draft → submitted → approved → scheduled → assigned → in_transit → delivered`، مع `cancelled` و`failed` حالتين نهائيتين بديلتين. | `Order` / `orders`، `OrderStatus`، `OrderType`، `OrderSource`، `OrderPriority` |
| الشحنة | Shipment | الجذر التجميعي (aggregate root) لحركة البضائع من مستودع المصدر إلى مستودع الوجهة، ولها `reference_code` فريد، ووزن (`weight_kg`) وحجم (`volume_m3`)، وسائق ومركبة، و`equipment_id` اختياري، و`price_sar`. دورة حياتها: `created → ready → assigned → picked_up → in_transit → delivered`، و`delayed` حالة مصاحبة أثناء النقل، و`failed` تسمح بـ `returned`، و`cancelled` متاحة من أي حالة قبل التسليم. | `Shipment` / `shipments`، `ShipmentStatus`، `ShipmentPriority` |
| الشحنة النشطة | Active shipment | شحنة حالتها ضمن `created`, `ready`, `assigned`, `picked_up`, `in_transit`, `delayed`؛ تُحتسب في حمل المستودع وفي حصرية السائق والمركبة. | `ACTIVE_STATUSES` (`app/services/shipment_service.py`) |
| الإسناد | Assignment | ربط سائق متاح (`is_available`) ومركبة حالتها `active` بشحنة، مع ضبط `assigned_at` والانتقال إلى `assigned`. حصري على مستوى الشحنات النشطة، ويمر ببوابة الإسناد. | `ShipmentService` |
| انتقال الحالة | Status transition | تغيير حالة مسموح وفق آلة الحالات؛ الانتقال غير المشروع يرفع `StatusTransitionError`. | `ShipmentStateMachine`، `OrderStateMachine`، `StatusTransitionError` |
| حدث التتبع | Tracking event | سجل إلحاقي فقط (append-only) مرتب زمنيًا على الشحنة، نوعه أحد: `status_update`، `location_update`، `proof_of_delivery`، `exception`، ويحمل `event_time` وإحداثيات و`evidence_url` اختياريًا. | `ShipmentTrackingEvent` / `shipment_tracking_events`، `TrackingEventType` |
| إثبات التسليم | Proof of delivery (POD) | حدث تتبع من نوع `proof_of_delivery` مرفق به `evidence_url`. | `TrackingEventType.PROOF_OF_DELIVERY` |
| عرض الشحنة | Offer | شحنة بحالة `ready` تُعرض على السائق في التطبيق للقبول أو الرفض ضمن نافذة زمنية (15 ثانية افتراضيًا في التطبيق). | `GET /shipments/nearby`، `ShipmentOfferRead` |

## الأسطول والمستودعات

| المصطلح العربي | English term | التعريف | Code identifier |
|---|---|---|---|
| السائق | Driver | الملف التشغيلي لمستخدم بدور `driver`: `license_number` و`license_class` و`phone_number` و`is_available` و`home_warehouse_id`. | `Driver` / `drivers` |
| المركبة (الشاحنة) | Vehicle | أصل نقل له `plate_number` و`vin` وسعة وزن (`capacity_weight_kg`) وحجم (`capacity_volume_m3`). حالتها `active`/`maintenance`/`decommissioned`، ولا يُسند إلا ما حالته `active`. | `Vehicle` / `vehicles`، `VehicleStatus` |
| المستودع | Warehouse | عقدة مادية بموقع جغرافي وسعة وزن وحجم و`max_daily_shipments`. | `Warehouse` / `warehouses` |
| السعة | Capacity | حدود الوزن (kg) والحجم (m³) للمستودع أو المركبة، تُتحقق قبل الإنشاء والإسناد. | `capacity_weight_kg`، `capacity_volume_m3` |

## المعدات والأصول

| المصطلح العربي | English term | التعريف | Code identifier |
|---|---|---|---|
| فئة المعدات | Equipment category | عقدة في شجرة تصنيف المعدات قابلة للتوسع، ومحصورة بالمستأجر (`parent_id`). | `EquipmentCategory` / `equipment_categories` |
| طراز المعدات | Equipment model | مدخل كتالوج: قالب مواصفات لصانع وطراز ضمن فئة. | `EquipmentModel` / `equipment_models` |
| وحدة المعدات | Equipment (unit) | معدة ثقيلة مادية هي موضوع الحركة (ADR-009): أبعاد ووزن، ونوع ملكية (`owned`/`leased`/`customer_owned`/`third_party`)، وأعلام `requires_permit` و`requires_escort` و`hazardous` و`insurance_required`. حالتها: `active`/`inactive`/`under_maintenance`/`reserved`/`in_transit`/`decommissioned`. | `Equipment` / `equipment`، `EquipmentStatus`، `EquipmentOwnershipType` |
| توفر المعدات | Equipment availability | التوفر التشغيلي للوحدة، منفصل عن حالتها: `available`/`reserved`/`unavailable`/`assigned`/`maintenance`. تبدأ كل وحدة جديدة بـ `available`. | `Equipment.availability_status`، `EquipmentAvailability` |

## الامتثال والتصاريح

| المصطلح العربي | English term | التعريف | Code identifier |
|---|---|---|---|
| التصريح | Permit | تصريح حركة لشحنة زائدة الأبعاد أو الوزن أو خاصة، له نافذة صلاحية (`valid_from`/`valid_until`). أنواعه: `oversize`، `overweight`، `government`، `municipal`، `special_movement`، `site_entry`. دورة حياته: `draft`، `submitted`، `under_review`، `approved`، `active`، والنهائية `rejected`/`expired`/`cancelled`. | `Permit` / `permits`، `PermitStatus`، `PermitType`، `PermitStateMachine` |
| المرافقة | Escort | خطة مرافقة لحركة زائدة الأبعاد: `private_escort`، `police_escort`، `pilot_vehicle`، `technical_support`. حالتها `planned`/`scheduled`/`cancelled`/`completed`. | `Escort` / `escorts`، `EscortType`، `EscortStatus` |
| قيد المسار | Route restriction | قيد طريق جغرافي أو حسب الخاصية يُقيَّم عند الإسناد: حد وزن أو ارتفاع أو عرض أو طول، أو نافذة زمنية، أو مواد خطرة، أو إغلاق طريق. | `RouteRestriction` / `route_restrictions`، `RouteRestrictionType` |
| ملف أوزان المحاور | Axle weight profile | توزيع الوزن على المحاور لتركيبة معدة + مركبة، مع علم امتثال. | `AxleWeightProfile` / `axle_weight_profiles` |
| فحص الامتثال | Compliance check | نتيجة تقييم امتثال واحد لحركة: نوعه (مثل `permit_required`، `axle_weight`، `route_restriction`، `operator_certification`، `insurance_required`) وحالته (`pending`/`passed`/`failed`/`warning`/`overridden`) وعلم `blocking` (افتراضيًا `true`) و`failure_reasons`. | `ComplianceCheck` / `compliance_checks`، `ComplianceCheckType`، `ComplianceCheckStatus` |
| بوابة الإسناد | Dispatch gate | تقييم للقراءة فقط تستدعيه خدمة الشحنات قبل الإسناد. يمرر الشحنات بلا معدات، ويُغلق عند الشك (fail closed) للمعدات التي تتطلب تصريحًا أو الخطرة أو الزائدة الأبعاد ما لم يوجد تصريح `active` ساري، أو عند اشتراط مرافقة غير مجدولة، أو عند وجود فحوص امتثال فاشلة حاجبة. اشتراط التأمين تحذير استشاري فقط. | `ComplianceValidationService.validate_dispatch` → `DispatchGateResult` (`app/services/compliance_service.py`) |
| شهادة المشغّل | Operator certification | شهادة لمستخدم تحدد أهليته لتشغيل فئة معدات، بنافذة صلاحية. حالتها `active`/`expired`/`suspended`/`revoked`. | `OperatorCertification` / `operator_certifications`، `OperatorCertificationStatus` |

## التأمين والمطالبات

| المصطلح العربي | English term | التعريف | Code identifier |
|---|---|---|---|
| وثيقة التأمين | Insurance policy | وثيقة لدى مزود تأمين بنوع (`cargo`، `equipment_in_transit`، `third_party_liability`، `project_car_ear`، `marine_inland`) وفترة تغطية ومبلغ تغطية وتحمّل. حالتها `draft`/`active`/`suspended`/`expired`/`cancelled`. | `InsurancePolicy` / `insurance_policies`، `InsurancePolicyType`، `InsurancePolicyStatus` |
| قاعدة التغطية | Coverage rule | قاعدة ضمن الوثيقة تحدد ما يُغطى (`CoverageType`) لنوع بضاعة أو فئة معدات، بحد أقصى وتحمّل واستثناءات، وقد تشترط `requires_compliance_clearance`. | `CoverageRule` / `coverage_rules`، `CoverageType` |
| المطالبة | Claim | مطالبة تأمينية مرتبطة بوثيقة وبشحنة أو طلب أو معدة، بنوع وشدة ومبلغ مطالب ومبلغ معتمد. سير عملها: `created → under_review → approved/rejected`، ثم `approved → settled → closed` و`rejected → closed`، ويمكن إعادة فتح `closed` إلى `under_review`. | `Claim` / `claims`، `ClaimStatus`، `ClaimType`، `ClaimSeverity`، `ClaimStateMachine` |
| تقرير الضرر | Damage report | توثيق ضرر مرتبط بمطالبة (بضاعة، معدة، مركبة، ممتلكات، نقص، تأخير) مع تكلفة تقديرية وصور وأدلة. | `DamageReport` / `damage_reports`، `DamageType` |
| سجل المسؤولية | Liability record | تحديد الطرف المسؤول في مطالبة (`customer`/`carrier`/`driver`/`company`/`third_party`/`unknown`) ونسبة المسؤولية ومبلغها. | `LiabilityRecord` / `liability_records`، `ResponsiblePartyType` |

## الفوترة والتسويات

| المصطلح العربي | English term | التعريف | Code identifier |
|---|---|---|---|
| عرض السعر | Quote | عرض سعر لعميل أو طلب أو شحنة بمبالغ فرعية وضريبة وخصم وإجمالي (العملة الافتراضية `SAR`). دورة حياته: `draft → issued → approved/rejected/expired/cancelled`. | `Quote` / `quotes`، `QuoteStatus` |
| الفاتورة | Invoice | فاتورة بمبالغ تشمل الغرامات وتعديلات المطالبات، وقد تكون إشعارًا دائنًا (`is_credit_note`). دورة حياتها: `draft → issued → partially_paid/paid/overdue/voided/cancelled`. | `Invoice` / `invoices`، `InvoiceStatus` |
| بند الفاتورة | Invoice line | بند ضمن فاتورة بنوع (`transport_fee`، `permit_fee`، `escort_fee`، `penalty`، `discount`، `tax`...) وكمية وسعر وحدة، ومرجع اختياري لكيان من نطاق آخر. | `InvoiceLine` / `invoice_lines`، `InvoiceLineType`، `LineReferenceType` |
| الدفعة | Payment | دفعة مستلمة على فاتورة بطريقة (`bank_transfer`/`cash`/`card`/`sadad`/`internal_adjustment`)، حالتها `pending`/`confirmed`/`failed`/`reversed`. | `Payment` / `payments`، `PaymentStatus`، `PaymentMethod` |
| التسوية | Settlement | تسوية تجارية (`claim_payout`، `claim_offset`، `customer_refund`، `carrier_payout`، `penalty_deduction`). دورة حياتها: `draft → pending_approval → approved → settled` مع إمكانية `cancelled` قبل التسوية. | `Settlement` / `settlements`، `SettlementStatus`، `SettlementType` |
| الصرف | Payout | صرف مالي ناتج عن تسوية، حالته `pending`/`paid`/`failed`. | `Payout` / `payouts`، `PayoutStatus` |
| الغرامة | Penalty | غرامة أو رسم إلغاء مرتبط بطلب أو شحنة أو فاتورة: `late_delivery`، `cancellation_fee`، `compliance_violation`، `damage`، `other`. | `Penalty` / `penalties`، `PenaltyType` |

## الإشعارات

| المصطلح العربي | English term | التعريف | Code identifier |
|---|---|---|---|
| قالب الإشعار | Notification template | قالب بـ `template_code` وقناة ولغة وقوالب عنوان ونص، مرتبط اختياريًا بنوع حدث. | `NotificationTemplate` / `notification_templates` |
| الإشعار | Notification | رسالة لمستلم عبر قناة (`in_app`/`email`/`sms`/`push`/`webhook`) بأولوية و`idempotency_key`. دورة حياتها: `pending → queued → sent → read`، مع `failed` (يعاد إلى `queued` عند إعادة المحاولة) و`cancelled`. | `Notification` / `notifications`، `NotificationStatus`، `NotificationChannel`، `NotificationPriority` |
| محاولة التسليم | Delivery attempt | سجل غير قابل للتعديل لمحاولة تسليم واحدة عبر قناة لدى مزود، نتيجتها `pending`/`succeeded`/`failed`/`skipped`/`retrying`. | `NotificationDeliveryAttempt` / `notification_delivery_attempts`، `DeliveryAttemptStatus` |

## الأحداث والقراءة (CQRS)

| المصطلح العربي | English term | التعريف | Code identifier |
|---|---|---|---|
| حدث النطاق | Domain event | حقيقة عمل وقعت على تجميعة (مثل إنشاء شحنة)، تُغلَّف وتُخزَّن في سجل الأحداث. | `DomainEvent` (`app/events/domain_event.py`) |
| غلاف الحدث | Event envelope | الوحدة الثابتة المخزنة والمنشورة: `event_id` و`tenant_id` و`aggregate_type` و`aggregate_id` و`aggregate_version` و`event_type` و`event_version` و`correlation_id` و`causation_id` و`user_id` و`occurred_at` و`metadata` و`payload`. | `EventEnvelope` (`app/events/envelope.py`) |
| مخزن الأحداث / صندوق الصادر | Event store / Outbox | سجل أحداث النطاق الإلحاقي غير القابل للتعديل، وهو نفسه صندوق الصادر المعاملاتي: تُكتب التجميعة والحدث في معاملة واحدة، ثم ينشر المرحّل (relay) الصفوف التي `published_at IS NULL`. ترتيب كل تجميعة مضمون بـ `UNIQUE(aggregate_id, aggregate_version)`. | `EventStore` / `event_store`، `OutboxRelayState` / `outbox_relay_state` |
| الحدث المعالَج | Processed event | سجل منع التكرار (idempotency) لكل مستهلك: الزوج `(consumer, event_id)` عولج مسبقًا، فيتحقق «تسليم مرة واحدة فعليًا». | `ProcessedEvent` / `processed_events` |
| الرسائل الميتة | Dead letter | حدث استنفد تسليمه لمستهلك ميزانية إعادة المحاولة، مع لقطة الحمولة وسبب الفشل وعدد المحاولات و`replayed_at` لإعادة التشغيل. | `DeadLetterEvent` / `dead_letter_events` |
| الإسقاط (نموذج القراءة) | Projection (read model) | جدول قراءة مُشتق من تدفق الأحداث لخدمة لوحات المعلومات؛ ليس مصدر الحقيقة التشغيلية، قابل لإعادة البناء من `event_store`، وغير خاضع للحذف الناعم أو قفل الإصدار. صحة كل إسقاط تُتتبع في `projection_health`. | `ShipmentPerformanceProjection`، `FinancialSummaryProjection`، `ARAgingProjection`، `ClaimsMetricsProjection`، `ComplianceMetricsProjection`، `NotificationDeliverabilityProjection`، `OperationsDashboardProjection` (`proj_*`)، `ProjectionHealth` |
| سجل التدقيق | Audit log | سجل إلحاقي فقط للفاعل والإجراء والصف المستهدف وحالته قبل التعديل وبعده. | `AuditLog` / `audit_log` |

## التكاملات الخارجية

| المصطلح العربي | English term | التعريف | Code identifier |
|---|---|---|---|
| شريك التكامل | Integration partner | جهة خارجية (`customer`/`carrier`/`vendor`/`government`/`internal`/`other`) تتكامل مع المستأجر. الشريك `suspended` لا يمكنه المصادقة. | `IntegrationPartner` / `integration_partners`، `IntegrationPartnerType`، `IntegrationPartnerStatus` |
| مفتاح API | API key | بيانات اعتماد محصورة بالمستأجر والشريك؛ يُخزَّن تجزيء bcrypt فقط مع `key_prefix`، ولها `scopes` و`allowed_ips` و`expires_at`. لا يصادق إلا المفتاح `active` غير المنتهي. | `PartnerApiKey` / `partner_api_keys`، `ApiKeyStatus` |
| اشتراك Webhook | Webhook subscription | اشتراك شريك في أنواع أحداث خارجية مُنقّحة إلى `target_url` (يخضع لحماية SSRF)، بسر توقيع مشفّر أثناء التخزين وخوارزمية `hmac_sha256`. لا يتلقى الأحداث إلا الاشتراك `active`. | `WebhookSubscription` / `webhook_subscriptions`، `WebhookSubscriptionStatus`، `SigningAlgorithm` |
| تسليم Webhook | Webhook delivery | Webhook صادر مُنقّح وموقّع في الطابور لاشتراك: `pending → delivering → delivered/failed`، ويمكن `cancelled` أو `skipped`. كل محاولة تُسجَّل سجلًا غير قابل للتعديل. | `WebhookDelivery` / `webhook_deliveries`، `WebhookDeliveryAttempt` / `webhook_delivery_attempts`، `WebhookDeliveryStatus`، `WebhookAttemptStatus` |
| الحدث الوارد | Inbound event | حدث يرسله شريك (POST) ويُدقَّق، وهو متساوي الأثر (idempotent) لكل مفتاح API + `idempotency_key`. دورة حياته: `received → accepted/rejected`، ثم `accepted → processed/failed`. | `InboundIntegrationEvent` / `inbound_integration_events`، `InboundEventStatus` |

## أنماط مشتركة

| المصطلح العربي | English term | التعريف | Code identifier |
|---|---|---|---|
| الحذف الناعم | Soft delete | يُعد الصف محذوفًا منطقيًا عند تعيين `deleted_at` مع الاحتفاظ ببياناته للتدقيق والاسترجاع. `soft_delete()` متساوية الأثر ولا تستبدل وقت الحذف الأول، و`restore()` تمسحه. على الاستعلامات إضافة `deleted_at IS NULL`. | `SoftDeleteMixin` (`app/db/mixins.py`)، `deleted_at`، `deleted_by` |
| القفل التفاؤلي | Optimistic locking (version) | عمود `version` يزيده SQLAlchemy عند كل تحديث (`version_id_col`)؛ الكاتب المتزامن يتلقى `StaleDataError` الذي تُترجمه الواجهة إلى HTTP 409. | `version`، `__mapper_args__ = {"version_id_col": version}` |
| حقول التدقيق | Audit fields | `created_by`/`updated_by` للمستخدم المنشئ والمحدِّث، و`created_at`/`updated_at` بتوقيت UTC. | `AuditMixin`، `TimestampMixin` |
