# مواصفة نظام التصميم — Mesaar

**الحالة: Planned مع أجزاء منفذة في تطبيق السائق.** التصميم داكن وعربي RTL أولًا.
[tokens.json](tokens.json) مواصفة Tokens؛ mobile/src/theme/ هوما يستورده التطبيق فعليًا.
القيم تدار يدويًا؛ لا Style Dictionary Pipeline أو مكتبة Web/Figma منفذة.

## المبادئ والقيم

واجهة هادئة تبرز بيانات التشغيل، وإعادة استخدام الألوان والمسافات والخطوط، و RTL مع إبقاء
الخرائط والشعارات والأرقام فياتجاه المحتوى. الكثافة Comfortable/Dense والوصول WCAG2.2AA
متطلبات تحتاج تنفيذًا وفحصًا، ولا تثبتها Tokens وحدها.

| الدور | Token | القيمة |
| --- | --- | --- |
| الخلفية | color.core.background | #090D14 |
| البطاقة | color.core.surface | #121821 |
| السطح المرتفع | color.core.surfaceElevated | #161D29 |
| الحدود | border/borderStrong | أبيض بعتامة 6%/12% |
| الإجراء | color.brand.primary | #2F6BFF |
| التركيز | color.brand.focusRing | #5C8DFF |
| النجاح/التحذير/الخطر/المعلومات | color.status.* | #18C56E/#FFB020/#FF5A5F/#3BA0FF |
| النص الرئيسي/الثانوي/الخافت | color.text.* | #F4F7FB/#7D8BA3/#5A6678 |

الخط العربي Tajawal؛ يقترح التصميم Inter للاتينية و JetBrains Mono للكود. التطبيق يحمل
Tajawal معبديل النظام. سلم النص display/h1/h2/h3/bodyStrong/body/caption/micro/numeric.
تنسيق الأرقام العربية في mobile/src/utils/format.ts. ألوان shipmentStatus تشمل 8 حالات؛
ينقصها picked_up و delayed. افحص التباين فوق الخلفية الفعلية ولا تعتمد على اللون وحده.

المسافات مضاعفات 4px، ونصف القطر 10–28، وارتفاعات الأزرار 36/44/56، وحد المس 24×24.
صفوف Comfortable52 و Dense40؛ Sidebar264 أو 72 عند الطي. هذه مواصفة وليست قياسًا لكل عنصر.
الظل shadow.* والترتيب z.* والحركة motion.*؛ احترم تقليل الحركة في Web و Native.

## الحالات و RTL

لكل تفاعل Default/Focus/Pressed/Disabled/Loading/Error/Selected، و Hover حين تدعمه المنصة.
لكل شاشة بيانات Loading/Empty/Error/No-permission إضافة إلى Default. المخزون الفعلي في
[فهرس المكونات](components-index.md).
استخدم CSS Logical Properties في Web، واعكس الأسهم الاتجاهية دون خرائط أو شعارات، واعزل
الهاتف والمعرّفات LTR. اختبر ترتيب التركيز وقارئ الشاشة بالعربية.

راجع [الشاشات](../ui/screen-map.md) و[قائمة الوصول](../docs/wcag-2.2-aa-checklist.md).
لا Axe في CI الحالي ولا شهادة مطابقة مكتملة.
