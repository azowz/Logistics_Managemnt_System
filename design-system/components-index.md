# فهرس المكونات — Logistic X

يفصل الفهرس بين Implemented في mobile/src/components/ و Planned للواجهات المستقبلية.
ظهور جزء داخل بطاقة لا يعني وجود مكون مستقل أوفحص كل حالاته. راجع [المواصفة](design-spec.md).

## المكونات المنفذة

| المكون | المسؤولية |
| --- | --- |
| AppLayout | المساحة الآمنة والخلفية والتمرير |
| AppText | النص وأنماطه وألوانه |
| Card | سطح البطاقة وحشوها |
| ErrorBoundary | احتواء خطأ العرض |
| PrimaryButton | فعل أساسي أو نجاح مع تحميل وتعطيل |
| SecondaryButton | فعل ثانوي وأيقونة |
| PhoneInput | هاتف سعودي LTR وخطأ التحقق |
| Toggle | تبديل التوفر |
| StatusCard | حالة الاتصال والتوفر |
| KPIBox | قيمة مؤشر وأيقونة |
| ShipmentRequestCard | المسار والحمولة والسعر |
| MapPreview | رسم مصغر للمسار |
| RouteMap | رسم SVG؛ ليس ملاحة حية |
| BottomNav | تبويبات؛ بعض الوجهات مخططة |
| CountdownBadge | عداد العرض وحلقة التقدم |
| OrderBottomSheet | ملخص العرض والقبول/التجاهل |
| DriverHeader | تعريف السائق والمركبة |

هذه قائمة ملفات التنفيذ؛ لا تعني دعم كل حالات الويب أو الوصول أو تشغيل Native مختبر.

## أجزاء مضمّنة

StatusPill و Badge و Chip/Tag و Avatar و Timeline و DescriptionList و InlineAlert و Drawer/BottomSheet
و EmptyState و ProgressBar/Ring و RouteStopCard و CompanyCard أنماط داخل شاشات أو بطاقات، وليست
كلها ملفات مستقلة. يستخرج الجزء حين يوجد تكرار حقيقي، لا لمجرد استكمال القائمة.

## المخزون المخطط

يحفظ الجدول نطاق المخزون السابق المكون من 65 عنصرًا تصميميًا، منفصلًا عن عدد ملفات التنفيذ.
العناصر الموجودة أعلاه قابلة للنقل بعد تكييفها للمنصة.

| الفئة | العناصر المخططة | الغرض |
| --- | --- | --- |
| الهيكل | AppShell، Sidebar/NavRail، TopBar، PageHeader | إطار Console، القائمة والبحث والمستأجر والعناوين |
| التنقل | Breadcrumb، Tabs، SegmentedControl، Pagination، CommandPalette، Stepper | السياق والأقسام والكثافة والصفحات والاختصارات وخطوات الحجز |
| النماذج | TextInput، PasswordInput، Textarea، Select/Combobox، MultiSelect، Autocomplete | إدخال وبحث واختيار واحد/متعدد |
| الخيارات والوقت | DatePicker/RangePicker، Checkbox/Radio، Slider، FileUpload | تواريخ وخيارات ونطاق ورفع POD/مستندات |
| الأفعال | IconButton، SplitButton/Menu | أيقونة وإجراء مع قائمة |
| البيانات | DataGrid، Table، FilterBar، StatCard/ChartCard، ActivityFeed | فرز وكثافة وفلاتر ومؤشرات وتدقيق |
| الاستجابة | Toast، Modal/Dialog، Tooltip/Popover، Skeleton | إشعار وتأكيد ومساعدة وتحميل |
| التشغيل | DispatchCard، VehicleChecklistCard، IncidentCard/ExceptionCard | أهلية الإسناد وفحص المركبة والاستثناءات |
| الخرائط والتحليل | LiveMapPanel، Sparkline، Chart | أسطول واتجاه ورسم خطي/عمودي/دائري |

لا مكتبة Web منفذة أو توليد تلقائي من[tokens.json](tokens.json). عند البناء أضف تحقق الحالات
والتركيز و RTL والوصول؛ الاسم بالمخزون لا يصنف Tested.
