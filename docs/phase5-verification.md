# تقرير المرحلة 5 — 2026-11-14

الحالة: مكتملة ضمن النطاق المتحقق على SDK 8.5.3. لم تبدأ Phase 6.
دليل الاستخدام والتوافق والرجوع في [phase5.md](phase5.md)
و[README](../README.md#arabic-runtime).

## نتائج فعلية

البيئة: Windows 11 x64، Python 3.13.12، PySide6/Qt 6.12.0، pytest 9.2.0،
fontTools **4.68.0**، Ren'Py **8.5.3.26051504** من مسار SDK الذي حدده المالك.

```powershell
$env:RAT_RENPY_SDK = 'D:\B\777\LC\renpy-8.5.3-sdk'
.\.venv\Scripts\python.exe scripts/build_windows.py
# pytest -c pyproject.toml tests ثم ruff check وruff format --check ثم التغليف
```

نتيجة بوابة البناء النهائية:

```text
332 passed in 75.27s
All checks passed!
156 files already formatted
BUILD_EXIT_CODE=0
```

لا فشل أو تخطٍ. أضيفت 32 حالة فوق مجموعة المرحلة 4 ذات الـ300 حالة. نجحت
المجموعة الكاملة قبل ذلك أيضًا: **332 passed in 73.06s**. سجل البناء الكامل
في `.local/phase5-build.log`. مجموعة المرحلة 5 الأولية: 30 passed in 25.65s،
ثم أضيف اختبار CLI واختبار التمييز بين المحارف المرئية وشيفرة المحميات.

## اختبار Ren'Py الفعلي

اختبار SDK أنشأ مشروعًا مؤلفًا محليًا من موارد RAT داخل staging، ولم يشغل Python
مستخرجًا من لعبة مستخدم. نجح **compile وlint**، ثم تشغيل **gl2** على Intel Iris Xe
ورسم لقطة فعلية. تحقق من:

- اتصال حروف Amiri والتشكيل الأصلي عبر HarfBuzz.
- الحوار واسم الشخصية والخيار ونماذج نصوص History وPreferences.
- بقاء Build 42 / 123 والأرقام العربية ٣٤٥ بترتيبها، والاستبدال الفعلي لـplayer_name.
- عرض الوسم b وإبقاء النص المنطقي والوسوم والمتغيرات دون قلب أو preprocessing.
- تعطيل حي وإعادة تفعيل وتغيير اللغة، واستعادة الخط والحجم وconfig.rtl السابقين.
- بدء تشغيل ثانٍ مع rat_runtime.disabled والتحقق من أن الطبقة غير نشطة.

راجعت بصريًا `.local/phase5-arabic-native.png` ولقطة التعطيل
`.local/phase5-arabic-disabled.png`. يختبر هذا السيناريو النصوص والأنماط القياسية
والرجوع؛ لا يعني المرور بكل شاشات أو مسارات لعبة تجارية أو كل قيم متغيراتها.

كشف الاختبار الفعلي مسألتين وعولجتا: callbacks اللغة تسبق إعادة تطبيق الأنماط
المؤجلة، لذلك استُخدم build_styles_callbacks مع حماية لقطة الأصل؛ كما أن أسماء
الخطوط ذات SHA كامل أطالت بعض مسارات Windows/SDL، فقُصّر اسم الأصل المصدّر مع
الإبقاء على البصمة الكاملة والتحقق من التصادم. لا تغير هذه المعالجة IDs الترجمة.

## EXE وموارد التوزيع

أعيد بناء `dist/RAT.exe` بنمط Windows GUI x64، الحجم **70,548,798 بايت**، وSHA256:

```text
73d84f4998663b282d360a98a5267dfe25dd39f2b2205779c48346a752cc438e
```

نُسخ وحده إلى `.local/phase5-exe-bae23b3a`، وشُغل من مجلد عمل فارغ مع حذف
PYTHONHOME وPYTHONPATH وVIRTUAL_ENV وحصر PATH في Windows System32. عاد برمز **0**
مع status=passed وfrozen=true، وتحقق من fontTools وموارد Amiri ورخصته وتوليد
Runtime والخطوط والمشروع التجريبي داخل النسخة المجمعة، إضافة إلى اختبارات
الفهرسة والحماية وMock والمراجعة والتصدير والنسخ الاحتياطي السابقة.
حُملت WinVaultKeyring وعملاء SDK وعامل Google دون مفتاح أو طلب API حقيقي.

نُسخ المشروع التجريبي الذي أنشأه **EXE نفسه** إلى مسار اختبار قصير مستقل:
`.local/phase5-native-0397915b`. نجح compile وlint وrun بواسطة SDK، وأكد
mixed_text_preserved=true وstyles_restored=true. سجلاته في
`.local/phase5-frozen-compile.log`, `phase5-frozen-lint.log`, `phase5-frozen-run.log`.
النتيجة الكاملة، بما فيها مسار المشروع وبصمة EXE، في `.local/phase5-exe-check.json`.

بُنيت wheel أيضًا وتحقق فهرس ZIP من تضمين ملف الخط وOFL ومصدر العينة ودليلها.
التشغيل المستقل تحقق على الجهاز الحالي؛ لم يتوفر Windows نظيف لاختبار جهاز آخر.

## ما أضيف وما عُدّل

| الملفات الجديدة | الوظيفة |
|---|---|
| `src/rat/domain/arabic.py` | عقود الخطوط والتوافق والأحجام والإعدادات ونتائج الفحص. |
| `src/rat/arabic/fonts.py` | cmap والمحارف العربية وجداول التشكيل والقيود والترخيص وFontGroup ranges. |
| `src/rat/arabic/rtl_profiles.py` | ملفات توافق الإصدار وفصل دليل اللعبة عن SDK والتحقق اليدوي. |
| `src/rat/arabic/style_generator.py` | توليد arabic_runtime.rpy مستقل وRTL/HarfBuzz وأنماط الأدوار والرجوع. |
| `src/rat/arabic/runtime.py` | حفظ الخيارات واستيراد الخطوط الموثقة وبناء ملحق التصدير والعينة. |
| `src/rat/arabic/preview.py` | معاينة tokenizer آمنة وقيم متغيرات تجريبية دون تنفيذ تعبيرات. |
| `src/rat/ui/pages/arabic_settings.py` | اختيار الخط والاحتياطيات والأحجام والاتجاه والتوافق والمعاينة والعينة. |
| `src/rat/resources/fonts/amiri/Amiri-Regular.ttf`, `OFL.txt` | خط أصلي مرخص ونص الرخصة الكامل. |
| `src/rat/resources/arabic_demo/game/script.rpy`, `README_AR.txt` | مشروع Ren'Py تجريبي أصلي مع اختبارات تشغيل وتعطيل ودليل. |
| `assets/fonts/README.md` | توثيق مصدر الخط وموقع المورد والترخيص. |
| `tests/unit/test_arabic_runtime.py` | 21 حالة للخطوط والتوافق والأحجام والوسوم والمعاينة والترميز. |
| `tests/integration/test_arabic_runtime_flow.py` | 7 حالات لحفظ الخطوط والنسخ الاحتياطي والتصدير والرجوع وSDK. |
| `tests/integration/test_arabic_commands.py` | فحص CLI والتعطيل دون تخمين الإصدار. |
| `tests/ui/test_arabic_settings_page.py` | 3 حالات للمعاينة والتحذير والحفظ والفتح والتعطيل عبر Qt. |
| `docs/phase5.md`, `docs/phase5-verification.md` | الدليل والنطاق والتقرير. |

الملفات المعدلة:

- `src/rat/config/models.py`: RuntimeOptions اختياري معطّل افتراضيًا واتجاه ltr إضافي؛
  إعدادات الحماية وlegacy_preprocess المعطّل لم تُخفف.
- `src/rat/discovery/version_detector.py`: قراءة metadata إصدار JSON دون تنفيذ شيفرة.
- `src/rat/domain/review.py`: بيان Runtime داخل تقرير التصدير، مع دعم التقارير الأقدم.
- `src/rat/exporters/manager.py`: تضمين Runtime والخطوط والتراخيص وبياناتها في manifest
  وZIP والتقرير؛ منع إخراج الترجمات عند فشل الطبقة المطلوبة.
- `src/rat/exporters/backup.py`: تضمين الخطوط المستوردة وتراخيصها والتحقق من بصماتها.
- `src/rat/ui/main_window.py`, `ui/pages/export.py`: ربط صفحة العربية وحالة الانشغال
  وتحديث وصف التصدير دون منطق استخراج أو HTTP في UI.
- `src/rat/cli/commands.py`: أمر arabic للفحص وإعداد YAML والتعطيل والعينة، وبيان Phase 5.
- `src/rat/desktop_checks.py`: فحص موارد الخط وRuntime والعينة داخل EXE، دون API.
- `pyproject.toml`: fontTools ومورد الخط والعينة ضمن package-data، دون مكتبات reshaping.
- `requirements-dev-windows-py313.lock.txt`, `requirements-windows-build-py313.lock.txt`:
  إضافة الإصدار المختبر fonttools 4.68.0.
- `scripts/RAT.spec`: موارد الخط والعينة وواردات fontTools الديناميكية.
- `scripts/collect_licenses.py`: تضمين نص OFL ضمن إشعارات EXE.
- `README.md`, `docs/architecture.md`, `docs/compatibility.md`, `docs/windows-exe.md`:
  شرح المبتدئين والتوافق وقرارات التوليد والرجوع ونتائج التغليف.
- `dist/RAT.exe` وwheel: نواتج التوزيع المحدّثة.

لم يتغير مخطط SQLite v4 أو نصوص المصدر أو IDs أو old. اختبارات المرحلتين 2 و4
بقيت ناجحة، وتحقق اختبار التصدير من بقاء كل بايت في أصل عينة اللعبة دون تغيير.

## حدود التحقق

- لم تختبر إصدارات أخرى حيًا أو لعبة تجارية. 7.x و8.0/8.1 تبقى محجوبة، وكذلك
  سلسلة 8.3.7 للمشكلة المعروفة. لا يوجد legacy reshaping غير متحقق أو تحديث محرك.
- أنماط الشاشات ووسوم font المخصصة وقيم متغيرات جديدة قد تحتاج إعدادات أو خطوطًا
  إضافية. Qt معاينة تقريبية؛ ليست إثباتًا لمظهر اللعبة الفعلي.
- تصريح المستخدم ونص الترخيص مطلوبان للخط المخصص؛ الفحص التقني وحده لا يثبت حق توزيعه.
- تعطيل Runtime يستعيد الأنماط ويحفظ الترجمات؛ لا يزيل ملفات حزمة قديمة تلقائيًا.
- لا تثبيت أو فك أرشيفات أو مزودات Phase 6، ولا اختبار حساب API حقيقي في هذه المرحلة.
