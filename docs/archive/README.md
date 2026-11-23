# الأرشيف التاريخي

وثائق التصميم وتقارير المراحل كما كُتبت وقت إعدادها (بالإنجليزية). **لا تصف الحالة الحالية**:
بعض ما فيها لم يُنفذ، وبعضه نُفذ بشكل مختلف، وأعداد الاختبارات ودرجات الجاهزية فيها لقطات قديمة.
المرجع الحالي هو التوثيق العربي في [docs/](../README.md).

حُفظت لأنها تحمل أسباب القرارات وتصاميم مجالات لم تُنفذ بعد. كانت سابقًا في `docs/NN-*.md`،
وأي إشارة قديمة إلى `docs/NN` (مثلًا في docstrings الترحيلات التي لا تُعدَّل) تعني `docs/archive/NN`.

| الملف | النوع | المرجع الحالي |
| --- | --- | --- |
| `01-project-vision.md` (+ `.docx`) | رؤية المنتج | [vision.md](../vision.md) |
| `02-architecture.md` | مسودة المعمارية (المرحلة 2) | [architecture.md](../architecture.md) |
| `03-database-architecture.md` | تصميم قاعدة البيانات المستهدف | [database.md](../database.md) |
| `04-event-storming-and-state-machines.md` | Event Storming وآلات حالات مصممة (تختلف عن المنفذ) | [domains.md](../domains.md) |
| `05-backend-architecture.md`، `11-backend-architecture.md` | مخطط الطبقات والمرحلة 8 | [architecture.md](../architecture.md) |
| `06-architecture-audit-and-readiness.md` | تدقيق المرحلة 4.5 (يضيف تصميم إدارة العقود) | [status.md](../status.md) |
| `07-phase-5-execution-plan.md`، `12-implementation-plan.md`، `17-execution-roadmap.md` | خطط تنفيذ متعاقبة | [status.md](../status.md) |
| `08-heavy-equipment-domain-design.md` | تصميم المعدات والامتثال والتأمين | [domains.md](../domains.md)، ADR-008/009 |
| `09-final-domain-model.md`، `09a-reconciliation-and-closure.md` | نموذج المجالات الموحد (المرحلة 6) | [domains.md](../domains.md) |
| `10-final-erd-review.md` | مراجعة ERD حتى الترحيل 0003 | [database.md](../database.md) |
| `13-m2-readiness-report.md`، `14-m2-event-backbone.md` | تقارير العمود الفقري للأحداث | [architecture.md §5](../architecture.md#5-الأحداث-event-driven-transactional-outbox) |
| `15-enterprise-code-audit.md`، `16-implementation-readiness.md` | تدقيق كود وجاهزية (2026-06) | [status.md](../status.md) |
| `18-…` حتى `28-…` | تقارير المجالات حسب السبرنت (الطلبات حتى التكاملات) | [domains.md](../domains.md) |
| `api-gap-analysis.md` | فجوات تطبيق السائق (معظمها أُغلق) | [status.md](../status.md) |
| `domain-glossary.md` | مسرد مصطلحات أولي | [glossary.md](../glossary.md) |
| `event-catalog.md` | كتالوج أحداث الشحنات (متجاوز) | [domains.md](../domains.md) |

لا تُحدَّث هذه الملفات. عند الحاجة لتغيير قرار، أنشئ ADR جديدًا في [adr/](../adr/README.md).
