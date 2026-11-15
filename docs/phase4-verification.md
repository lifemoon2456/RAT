# تقرير تنفيذ المرحلة 4 — 2026-11-14

الحالة: مكتملة ضمن نطاق محرر الترجمة وQA والتصدير. لم تبدأ Phase 5.
البيئة: Windows 11 x64، Python 3.13.12، PySide6/Qt 6.12.0، pytest 9.2.0.
التصميم والاستخدام في [phase4.md](phase4.md) و[README](../README.md#editor).

## النتائج الفعلية

```powershell
$env:RAT_RENPY_SDK = 'D:\B\777\LC\renpy-8.5.3-sdk'
.\.venv\Scripts\python.exe scripts/build_windows.py
# يتضمن: python -m pytest -c pyproject.toml tests
# ثم ruff check . وruff format --check . قبل PyInstaller
```

- pytest: **300 passed in 95.27s**، دون تخطٍ أو فشل؛ منها 48 حالة أضيفت في هذه المرحلة.
- Ruff: **All checks passed!**
- التنسيق: **143 files already formatted**.
- سجل التشغيل الكامل: `.local/phase4-build.log`، ويشمل التحقق ثم التغليف.
- نجحت قبل ذلك مجموعة مركزة من **47 اختبارًا في 34.32s** للمحرر والجودة والبدائل
  والتصدير وأوامر CLI وترقية قاعدة Phase 3. أعيد التحقق من الكل قبل التغليف.

الاختبارات الحية تستخدم SDK **Ren'Py 8.5.3.26051504** الذي حدده المالك؛
توليد القوالب على staging مستقل واختبار التصدير على نسخة من عينة RAT المؤلفة
محليًا، دون تشغيل Python مستخرج من لعبة. جرى compile ثم تشغيل أمر تشخيص مؤلف
للاختبار داخل النسخة فقط؛ أكد تحميل ستة معرفات حوار وسلسلتي old/new ومطابقة
النصوص العربية واستبدال `[player_name]` بقيمة فعلية. كشف ذلك فرق escaping بين
حوار Ren'Py وPython literals في old/new، وصُحح المحلل والكاتب مع اختبار رجوع.

التصدير ثم الاستيراد إلى مشروع جديد حافظ على كل النصوص والـIDs وold والترجمات
للثماني وحدات. قورنت بصمات كل ملفات أصل العينة قبل العمليات وبعدها ولم تتغير.
اختُبر أيضًا QA الحاجز، ورفض اعتماد جماعي معطوب، وسجل الاعتماد، وتعارض الحفظ،
والقفل أثناء وصول نتيجة المزود، والبدائل دون تغيير المعتمد، وعدم إعادة استخدام
المعتمد لمصدر متغير، واللقطات المعطوبة، ومسارات Windows غير الآمنة، وZIP،
والتصدير عند غياب الأصل بعد الالتقاط، والتحقق من نسخة SQLite الاحتياطية وفسادها.

اختبارات Qt عبر offscreen تشمل الحفظ التلقائي وحفظ المسودة عند إغلاق المشروع،
والبحث والسياق والإجراءات الجماعية والقفل وطلب بدائل وتطبيقها والتصدير الخلفي.
أُخذت معاينة إضافية عبر منصة Qt الأصلية windows بخط النظام في
`.local/phase4-editor.png`؛ هي فحص واجهة RAT وليست فحص العربية داخل لعبة.

## النسخة التنفيذية المستقلة

أعيد بناء `dist/RAT.exe` بحجم **68,395,676 بايت** وSHA-256:
`3f134b2530b1ac08ebf40c3352bc781435d329772817f3f81cf666e55584b76d`.
نُسخ وحده إلى `.local/phase4-exe-bad22aba` وشُغّل من مجلد عمل فارغ، مع إزالة
PYTHONHOME وPYTHONPATH وVIRTUAL_ENV وحصر PATH في Windows System32. نجح برمز **0**
مع `frozen: true` و`review_qa_verified`, `export_verified`, `backup_verified`،
إضافة إلى حماية النصوص وMock وإعادة فتح المشروع وتراخيص المكتبات.
SDK خارجي اختياري، واستخدم في هذا الفحص من مسار المالك. فُهرست 317 وحدة وصُدّرت
وحدتا العينة المعتمدتان؛ لم يتغير أصل العينة. حُملت عملاء SDK وWinVaultKeyring
وعامل Google دون طلب API أو مفتاح حقيقي. النتيجة الكاملة في
`.local/phase4-exe-check.json` وشرح البناء في [windows-exe.md](windows-exe.md).

## قائمة الملفات الجديدة

| الملفات | الوظيفة |
|---|---|
| `src/rat/domain/review.py` | الحالات وعقود المحرر وQA والبدائل وتقرير التصدير وأعداده. |
| `src/rat/review.py` | التحرير والاعتماد والرفض والتجاهل والقفل والسياق والبدائل. |
| `src/rat/database/review_repository.py` | الحالة الحالية وسجل المراجعات وتعارض الحفظ والبدائل. |
| `src/rat/translation/quality.py` | فحوص QA الحاجزة والتحذيرات وتقدير تجاوز الواجهة. |
| `src/rat/exporters/manager.py` | اختيار السطور وفحصها وإنتاج الحزمة والتقارير وZIP وسجل التصدير. |
| `src/rat/exporters/renpy_writer.py` | كتابة translate وstrings مع المعرفات الأصلية وفحص إعادة القراءة. |
| `src/rat/exporters/templates.py` | لقطة قوالب موثقة ومقيدة ببصمات الاستيراد. |
| `src/rat/exporters/safe_io.py` | مسارات مستقلة ومنع الاجتياز والروابط والأسماء المحجوزة والتداخل مع الأصل. |
| `src/rat/exporters/backup.py` | SQLite backup للمشروع وmanifest والتحقق من البصمات. |
| `src/rat/ui/widgets/editor_table.py` | جدول قابل لتحرير الترجمة والبحث والتصفية. |
| `src/rat/ui/pages/review.py` | صفحة المحرر والمراجعة والسياق والبدائل الكاملة. |
| `src/rat/ui/pages/export.py` | صفحة التصدير والنسخ الاحتياطي والتقرير. |
| `tests/unit/test_quality.py` | حالات QA والفساد والتحذيرات. |
| `tests/integration/test_review.py` | الحفظ والتاريخ والقفل والاعتماد وإعادة الفهرسة. |
| `tests/integration/test_review_alternatives.py` | البدائل وحفظ المعتمد وحواجز التزامن. |
| `tests/integration/test_renpy_export.py` | التصدير وإعادة الاستيراد والهروب وSDK والنسخ الاحتياطي والمسارات. |
| `tests/integration/test_phase4_commands_migration.py` | أوامر CLI في عمليات منفصلة وترحيل v3 إلى v4. |
| `tests/ui/test_review_export_pages.py` | عمليات المحرر والتصدير الفعلية عبر Qt. |
| `docs/phase4.md`, `docs/phase4-verification.md` | النطاق والشرح وهذا التقرير. |

## الملفات المعدلة

- `src/rat/database/tables.py`, `migrations.py`: خمسة جداول جديدة ومخطط v4،
  وترقية النسخ 1/2/3 مع نسخة احتياطية قبل التغيير.
- `src/rat/database/repositories.py`: لا اعتماد عبر واجهة الحفظ القديمة دون QA،
  ولا تجاوز لقرارات المراجع عبر هذه الواجهة.
- `src/rat/database/translation_repository.py`, `src/rat/translation/orchestrator.py`:
  اختيار وحدات معينة، وحماية المراجعات والقفل عند الطلب والحفظ، وتخزين بدائل منفصلة.
- `src/rat/domain/translation.py`, `src/rat/providers/structured.py`:
  خيارات البدائل وTM ورقم الصياغة ضمن الطلب المنظم، دون تغيير عقد المزود.
- `src/rat/extraction/translation_parser.py`: فك old/new وفق Python literals الثابتة
  دون eval أو تنفيذ تعبيرات، بما يطابق SDK ويحفظ الفراغات والهروب.
- `src/rat/ui/main_window.py`, `ui/pages/game_import.py`, `ui/task_worker.py`:
  ربط الصفحات وتحديثها وإدارة الانشغال وحفظ المسودة قبل الإغلاق ورسائل أخطاء آمنة.
- `src/rat/cli/commands.py`: أوامر qa/export/backup وبيان Phase 4.
- `src/rat/desktop_checks.py`: تحقق النسخة المجمعة من المراجعة وQA والتصدير والنسخ الاحتياطي.
- `tests/integration/test_game_import.py`, `test_persistence.py`,
  `test_translation_manager.py`: تحديث ترقية v4 وأمثلة الاعتماد القديمة لتحتفظ
  بالمحميات؛ لم تُخفف فحوص سلامة الأصل أو الصفوف المعتمدة.
- `tests/unit/test_extraction.py`: اختبار مستقل لدلالات old/new ورفض التعبيرات التنفيذية.
- `scripts/build_windows.py`, `scripts/dev.ps1`: تحديد config ومجلد tests صراحةً
  لضمان تحميل conftest في مسار Windows الحالي ذي المسافات والفاصلة العليا.
- `README.md`, `docs/architecture.md`, `docs/compatibility.md`, `docs/windows-exe.md`:
  تعليمات مبتدئين وقرارات التخزين والترميز وحدود التوافق والتغليف.
- `dist/RAT.exe`: نسخة الواجهة المستقلة المحدّثة؛ بيانات بنائها وفحصها في `windows-exe.md`.

## الحدود المتبقية

- لا تثبيت على اللعبة، أو استعادة فوق أصولها، أو إعداد RTL/خطوط؛ هذه أعمال مراحل لاحقة.
- لم يُختبر لعب بصري كامل أو لعبة تجارية أو محرك غير SDK 8.5.3 على الجهاز الحالي.
- التصدير يتطلب قوالب موثقة وتركيبًا مدعومًا؛ النصوص الخام ذات IDs المفقودة لا تُصدر
  بالتخمين، والكتل الجزئية أو المعطوبة محجوبة. دعم RPA/RPYC وruby والوسوم غير المسجلة
  لم يتوسع في هذه المرحلة.
- QA اللغوي والطول تقريبيان؛ لا يثبتان جودة المعنى أو خلو كل عبارة من بقايا إنجليزية
  أو ملاءمتها لقياس النافذة. الفحص البنيوي الحاجز يبقى إلزاميًا.
- لم تستخدم مفاتيح أو حسابات API حقيقية؛ اختبارات المزودات بمحاكاة HTTP وMock.
  طلب البدائل الحقيقي صريح وقد يستهلك رصيدًا، ولا يضمن المزود صياغات مختلفة.
- أول لقطة تصدير تتطلب الأصل والقوالب المطابقة. النسخة الاحتياطية لمشروع RAT فقط،
  لا لملفات اللعبة أو مفاتيح النظام. لا توجد واجهة استعادة تلقائية في Phase 4.
