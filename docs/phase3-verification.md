# تقرير تحقق المرحلة 3 — 2026-11-14

**التنفيذ متاح؛ التحقق من حسابات API الحقيقية معلّق لعدم توفر مفاتيح اختبار.**
لم تُنفذ المرحلة 4، ولم تُعدل أصول لعبة أو يُنتج تعريب قابل للتثبيت.

## النتائج الفعلية

البيئة: Windows 11 x64، Python 3.13.12، PySide6/Qt 6.12.0.
المكتبات المثبتة والمختبرة: OpenAI 2.54.0، google-genai 1.75.0، deep-translator 1.11.4.
استُخدم Ren'Py SDK المالك 8.5.3.26051504 لاختبار قوالب المرحلة 1 دون تغيير مصدرها.

| الفحص | النتيجة |
|---|---|
| pytest قبل اختباري التكامل الأخيرين | 250 passed in 34.38s |
| pytest النهائي ضمن سكربت البناء | **252 passed in 37.65s**، دون فشل أو تخطٍ أو تحذيرات |
| ruff check | `All checks passed!` |
| ruff format --check | نجاح فحص التنسيق |
| pip check | `No broken requirements found.` |
| PyInstaller | نجاح بناء EXE يتضمن SDK الاختيارية وواجهات المرحلة 3 |
| EXE المنقول منفردًا | رمز خروج 0، `frozen: true`، مع تحقق محرك الترجمة والعامل الفرعي |

أمر التحقق النهائي:

```powershell
$env:RAT_RENPY_SDK = 'D:\B\777\LC\renpy-8.5.3-sdk'
.\.venv\Scripts\python.exe scripts/build_windows.py
```

يشغل البناء pytest وruff وفحص التنسيق وجمع التراخيص ثم PyInstaller.
يمكن تشغيل الاختبارات مباشرة دون البناء:

```powershell
.\.venv\Scripts\python.exe -m pytest -c pyproject.toml --renpy-sdk="D:\B\777\LC\renpy-8.5.3-sdk"
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
```

## ما أثبتته الاختبارات

- واجهة ABC موحدة تحفظ عقد TranslationProvider، وSDK OpenAI فعلية خلف
  HTTP MockTransport لكل من OpenAI وDeepSeek وOpenRouter وCustom.
- Gemini SDK فعلية مع HTTP محاكى، وJSON Schema وusage، وجلب الموديلات من
  صفحات SDK لكل من OpenAI وGemini دون أسماء ثابتة.
- رفض JSON غير الصالح والمعرفات الناقصة والمكررة والأجنبية والنص غير الصحيح.
  تتبع الدفعات unit_id عند عكس ترتيب الرد؛ لا تعتمد ترتيب القوائم.
- محرك **120 وحدة** على Mock: توقف بعد 8 نتائج، ثم استأنف الباقي من **عملية CLI
  جديدة** دون تكرار revisions؛ ظل Translated صفرًا وSimulated=120.
- مسار كامل من المصدر إلى الحماية وOpenAI SDK وHTTP محاكى ثم الاستعادة والحفظ؛
  حُفظت النصوص الناتجة مع رموزها الأصلية، دون إرسال `[name]` خامًا في الطلب أو السياق.
- BatchManager يراعي العدد والميزانية التقريبية وUTF-8 والسياق والقاموس وحجز المخرج،
  ويبلغ عن العنصر الأكبر من الحد دون إسقاط العناصر التالية.
- RetryManager يطبق backoff وRetry-After لأخطاء مؤقتة، ولا يعيد المصادقة والأخطاء
  النهائية. توقف المصادقة توزيع دفعات جديدة، وتبقى الوحدات الباقية للاستئناف.
- حد تزامن ومعدل طلبات قابل للاختبار بساعة وانتظار محاكيين.
- رفض نتيجة فاقدة الحماية على مستوى الوحدة، مع حفظ الوحدات السليمة الأخرى.
  تقسم استجابة IDs المعيبة إلى وحدات أصغر حتى تتعافى الحالات الصالحة.
- glossary CSV يحفظ أسماء مقفلة حرفيًا، ولا يغير PH أو أجزاء الأسماء الأطول؛
  ترفض علامات GL المعدلة أو مصادر/أهداف مصطلحات تحتوي شيفرة Ren'Py.
- TM توحد 30 نصًا مكررًا في 5 مفاتيح سياق مختلفة، وتفصل اختلاف الشخصية/السياق
  والأسلوب والقاموس والموديل والمزود. محاكاة غير معتمدة يمكن أن تستبدلها مهمة
  حقيقية محاكية في الاختبار؛ لا تنتقل ذاكرة Mock إلى حساب API على أنها ترجمة.
- Pause/Stop/recovery للـin_progress، وحفظ المهمة وفتحها لاحقًا، ومنع تشغيل محركين
  على المشروع نفسه، ورفض قفل hard link قد يكتب في أصل لعبة.
- معاملة الدفعة تتراجع بالكامل عند فشل إدراج revision؛ لا تبقى ترجمة أو TM جزئية.
- ترقية قاعدة v2 إلى v3 مع backup والتحقق من المصدر، وتحديث اختبار ترقية v1.
- حماية approved وعدم مسحها عند الاستئناف وتغير المزود. مقارنة بايتات ملفات عينة
  اللعبة قبل الترجمة وبعدها، وبقاء المصدر والبصمات وسجل الوحدات كما هي.
- مفاتيح اختبار مصطنعة داخل vault محاكى فقط؛ لا تظهر في SQLite أو ملفات المشروع.
  ترفض مخازن غير معروفة دون plaintext fallback، ولا ينتقل مفتاح endpoint قديم إلى آخر.
- API logs تسجل فئات آمنة فقط؛ لا تظهر رسالة استثناء بعيدة تتضمن مفتاحًا مصطنعًا
  أو نص اللعبة. اختُبرت صفحة الاتصال المحلية والتقدم والاستئناف عبر Qt والعامل الخلفي.
- pytest لا يعتمد على اتصال خدمات ترجمة؛ تستعمل اختبارات الموصلات transports محاكية،
  وعامل Google محاكى، ومفاتيح مصطنعة.

## تحقق ملف EXE

الملف: `dist/RAT.exe`، الحجم **68,330,225 بايت**، Windows GUI x64.
SHA-256:

```text
b3034e96e6a4151b2ebb08ef38bb82f1c42667a6680c1f8ca271954bb7e18d20
```

نُسخ EXE وحده إلى مجلد مستقل وشُغّل من مجلد فارغ، مع إزالة PYTHONHOME/PYTHONPATH/
VIRTUAL_ENV وحصر PATH في System32. أكد التقرير:

- فتح Qt وإنشاء مشروع وإغلاقه وإعادة فتحه، وجرد المصدر وتوليد قوالب SDK الخارجي.
- الحماية والاستعادة ورفض نص فاقد العلامات.
- مهمة ترجمة Mock محفوظة من وحدتين، وإعادة تشغيلها دون تكرار.
- إنشاء وإغلاق عميلَي SDK OpenAI وGemini داخل النسخة المجمعة **دون أي طلب API**.
- تشغيل عامل Google المجمّع عبر EXE نفسه على قائمة عناصر فارغة **دون طلب شبكة**.
- تحميل `WinVaultKeyring` في النسخة المجمعة؛ لم يكتب التشخيص مفتاحًا في مخزن المستخدم.
- وجود التراخيص، ومنها رخصة deep-translator القديمة التي تقع في جذر dist-info.

التقرير المحلي `.local/phase3-exe-check.json`. التجربة على الجهاز الحالي عبر
Qt offscreen؛ ليست اختبار جهاز Windows نظيف، ولا اختبار API خارجي أو جودة ترجمة.

فُحصت معاينتان إضافيتان على منصة Qt الأصلية windows بنافذة لا تُعرض على الشاشة:
`.local/phase3-providers.png` و`.local/phase3-progress.png`. ظهرت حقول الإعداد
والمفتاح المخفي وأزرار الاختبار، وشاشة تقدم العينة مع Simulated=8 وTranslated=0.
هذه مراجعة للواجهة، وليست معاينة لتعريب داخل لعبة.

## الملفات الجديدة

- `src/rat/domain/translation.py`: إعدادات المزود والدفعات والقاموس والمخرجات والتقدم.
- `src/rat/providers/openai_compatible.py`, `openai.py`, `deepseek.py`, `openrouter.py`,
  `gemini.py`, `google_translate.py`, `google_worker.py`: الموصلات والعامل المعزول.
- `src/rat/providers/structured.py`, `settings_service.py`: مخطط الرد وبناء الطلب
  والتعامل الآمن مع الأخطاء وإعداد المزود واختبار الاتصال والموديلات.
- `src/rat/security/secrets.py`: مخزن المفاتيح الآمن دون fallback نصي.
- `src/rat/translation/orchestrator.py`, `batching.py`, `context.py`, `glossary.py`,
  `translation_memory.py`, `retries.py`, `rate_limits.py`, `api_logging.py`: المحرك ومكوناته.
- `src/rat/jobs/manager.py`: التحكم بالمهمة وقفل العملية.
- `src/rat/database/translation_repository.py`: ملفات المزود والمهام والذاكرة ومعاملة الدفعة.
- `src/rat/ui/task_worker.py`, `ui/pages/provider_settings.py`, `ui/pages/translation.py`:
  عامل الواجهة وصفحتا الإعداد والتقدم.
- `tests/unit/test_translation_components.py`, `test_providers_api.py`, `test_secrets.py`:
  اختبارات الدفعات/retry/الموصلات/القاموس/الذاكرة/الأسرار.
- `tests/integration/test_translation_manager.py`, `tests/ui/test_translation_pages.py`:
  سيناريو 120 وحدة والحفظ والاستئناف والترحيل والواجهة.
- `docs/phase3.md`, `docs/phase3-verification.md`: الدليل والعقود ونتائج التحقق.

## الملفات المعدلة

- `providers/base.py`, `mock.py`, `registry.py`: ABC وتسجيل المزودات وإغلاق الموارد.
- `config/models.py`: قبول معرفات المزودات الجديدة مع إبقاء الإعدادات غير السرية.
- `database/tables.py`, `migrations.py`: جداول providers/jobs/job_items/tm_entries ومخطط v3.
- `cli/commands.py`: أوامر providers وtranslate والاستئناف والإيقاف عبر Ctrl+C.
- `ui/main_window.py`: التبويبات ومنع تضارب العمل وحفظ الجاري عند طلب الإغلاق.
- `desktop_checks.py`: تحقق محرك الترجمة وSDK والعامل ومخزن Windows داخل EXE.
- `scripts/rat_desktop.py`, `RAT.spec`, `collect_licenses.py`: العامل المجمّع وbackend
  Windows الديناميكي وجمع تراخيص dist-info القديمة والحديثة.
- `pyproject.toml`: إضافة deep-translator إلى extra llm مع SDK المزودين.
- ملفات lock الخاصة ببيئة Windows: تحديث لقطة حزم المرحلة 3.
- `tests/unit/test_config.py`, `tests/integration/test_game_import.py`, `test_cli.py`:
  تحديث قبول الإعدادات وهدف الترحيل والتشخيص المجمّع.
- README وSTART_HERE ووثائق المعمارية والتوافق والمزودين والتشغيل ومعالجة المشكلات.
- `docs/phase2-verification.md`: رابط للتقرير اللاحق دون تغيير نتائج المرحلة السابقة.

لا تعديلات على AGENTS.md أو PROJECT_BLUEPRINT.md أو مصادر fixtures السابقة، ولا
أي لعبة أصلية. build/dist ولقطات التشخيص ملفات مولدة.

## ما لم يُتحقق منه وما لم يُنفذ

**لم يجر اتصال بحساب API حقيقي**، ولا طلب مدفوع أو اختبار مفتاح حقيقي، ولا
جودة ترجمة أو حدود حساب أو قائمة موديلات حقيقية. القبول الشبكي النهائي المذكور
في المخطط يظل معلقًا إلى أن يضيف المالك مفتاحه محليًا ويختبر طلبًا محدودًا صراحة.
لم يُختبر roundtrip لمفتاح حقيقي في WinVault؛ اختُبر عقد التخزين بالمحاكاة وتحميل backend.

Google Translate غير رسمي، ولا يدعم سياق/أسلوب LLM، وقد تتغير خدمته. تقدير tokens
تقريبي وحد المعدل خاص بالمهمة ودفعات المزود، ولا يمثل حصة عامة لكل طلب HTTP داخلي
في Google. لا يوجد حساب تكلفة مالية أو ضمان منع تكرار فوترة طلب غير محفوظ بعد الانقطاع.

لا يوجد fallback تلقائي أو ترجمة محلية أو Google Cloud رسمي. المراجعة اليدوية
وعرض الترجمة جنب الأصل والتصدير/ZIP/التثبيت وRTL داخل اللعبة تخص المراحل التالية.
لا يوجد ادعاء validated أو اكتمال تعريب؛ المنفذ يقبل البنية ويحفظ نتائج تحتاج مراجعة لغوية.
