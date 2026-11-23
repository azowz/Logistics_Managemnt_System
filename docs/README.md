# فهرس التوثيق

ابدأ من [README](../README.md) للتشغيل، ثم اقرأ بالترتيب الذي يناسب مهمتك:

أحدث تغيير: [جرد الفصل ومخططاته](separation-architecture.md)،
[الترحيل والتراجع](separation-migration.md)، و[نتائج الفصل الفعلية](../SEPARATION_REPORT.md).
مسارات `app/` و`tests/` في المراجع الخلفية أصبحت داخل `mesaar-backend/`.

| الملف | متى تقرؤه |
| --- | --- |
| [vision.md](vision.md) | فهم المنتج والمستخدمين والنطاق |
| [architecture.md](architecture.md) | الطبقات، دورة الطلب، تعدد المستأجرين، الأحداث، CQRS، إضافة مجال |
| [domains.md](domains.md) | مسؤوليات كل مجال، الكيانات، آلات الحالات، قواعد الأعمال، الأحداث، الواجهات |
| [database.md](database.md) | الجداول، العلاقات، RLS، الترحيلات، الفهارس، المعاملات |
| [api.md](api.md) | المصادقة، الأدوار، الترقيم، الأخطاء، توقيع طلبات الشركاء |
| [development.md](development.md) | إعداد البيئة، المتغيرات، الاختبارات، سير العمل |
| [operations.md](operations.md) | النشر، قائمة تحقق الإنتاج، المراقبة، استكشاف الأعطال |
| [status.md](status.md) | ما هو منفذ ومختبر ومخطط، المخاطر والديون التقنية |
| [review-report.md](review-report.md) | نتائج المراجعة والتحقق والتنظيف والأعداد المقاسة |
| [production-readiness-baseline.md](production-readiness-baseline.md) | إعادة التحقق الحالية وفجوات الجاهزية قبل التحسينات التالية |
| [glossary.md](glossary.md) | المصطلحات العربية/الإنجليزية ومقابلها في الكود |
| [adr/](adr/README.md) | القرارات المعمارية المعتمدة وأسبابها |
| [diagrams/](diagrams/) | مخططات Mermaid (السياق، النشر، ERD، آلات الحالات، التسلسل) |
| [wcag-2.2-aa-checklist.md](wcag-2.2-aa-checklist.md) | متطلبات الوصول للواجهات |
| [archive/](archive/README.md) | وثائق التصميم وتقارير المراحل التاريخية (ليست وصفًا للحالة الحالية) |

مواصفات الواجهات: [design-system/](../design-system/) و[ui/screen-map.md](../ui/screen-map.md)،
وتطبيق السائق المستقل: [mesaar-frontend/README.md](../mesaar-frontend/README.md).

**قاعدة التحديث:** التوثيق يصف الكود الفعلي. أي ميزة لا توجد في `app/` تُصنَّف Planned في
[status.md](status.md) حتى لو كانت مصممة بالتفصيل في الأرشيف.
