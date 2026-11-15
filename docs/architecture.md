# معمارية RAT — المراحل 0 إلى 6

## الحدود

`domain` يعرّف نماذج Pydantic v2 والحالات وعقد `TranslationProvider` غير المتزامن
بالصيغة المحددة في المخطط. الموصل يعيد `unit_id`, `translation_text`, `provider_id`,
`status` و`usage` عند توفر قياس موثوق. `providers/base.py` يعيد تصدير العقد نفسه
ويضيف BaseTranslationProvider مجردًا لتطبيقه، دون تغيير عقد translate_batch.

`ProjectService` في `src/rat/projects.py` ينظم إنشاء مساحة عمل جديدة وفتحها؛
هذا موضع إضافي لعمليات المشروع المشتركة بين UI وCLI، بدل وضعها في قاعدة البيانات
أو تكرارها في الواجهة. تنتهي اتصالات كل معاملة تلقائيًا، وتُغلق الجلسة عند إغلاق
المشروع أو النافذة. تعمل الفهرسة وتوليد القوالب عبر `QThread`/signals؛ لا توجد طلبات
HTTP أو منطق استخراج أو إدارة subprocess في UI.

حزم `discovery` و`extraction` وخدمات المسارات وواجهة الاستيراد منفذة في المرحلة 1.
حزمة `protection` منفذة في المرحلة 2، و`providers` و`translation` و`jobs` في
المرحلة 3؛ `review` وQA و`exporters` منفذة في المرحلة 4، و`arabic` في المرحلة 5.
أضيف تغليف الواجهة الحالية
في EXE مستقل لاحقًا بطلب مباشر من المالك، كما هو موثق في `windows-exe.md`.

## قرارات تأسيسية

- لا تستقبل خدمة إنشاء المشروع مسار لعبة في المرحلة 0. مساحة العمل منفصلة، ويستخدم
  مجلدها UUID داخليًا لا علاقة له بمعرّف ترجمة Ren'Py. اسم المشروع بيانات عرض فقط.
- يُكتب `project.yaml` أخيرًا باستبدال ملف مؤقت؛ إنشاء جزئي فاشل يبقى للفحص دون
  حذف تلقائي. الفتح يتحقق من النسخة والتطابق بين YAML وSQLite، ولا ينشئ قاعدة مفقودة.
  يستخدم اتصال SQLite وضع `rw` عند الفتح لمنع إنشاء ملف حتى لو حُذف بين الفحص والاتصال.
- `Settings` نماذج مجمدة مع `extra=forbid` وYAML آمن محدود الحجم. الأعلام التي تحمي
  أصول الألعاب والترجمات المعتمدة والتحقق من الرموز لا يمكن تعطيلها في هذه المرحلة.
  المزود الافتراضي `mock` لتجنب اتصال غير مقصود؛ الخدمات الحقيقية تتطلب اختيارًا
  وملف مزود ومفتاحًا محليًا عند الحاجة. التصدير مستقل داخل المشروع منذ المرحلة 4.
- لا تعالج إعدادات YAML أسرارًا. تحفظ SQLite عناوين الخدمة غير السرية وإعداداتها؛
  المفاتيح في مخزن النظام عبر keyring، ولا تدخل SQLite أو السجلات.
- ملفات الاعتماديات تعرّف llm لموصلات المرحلة 3 وcloud/offline للمستقبل. `requirements-core.txt` يثبت
  الحزمة المحلية كي تبقى قائمة اعتماديات التشغيل ذات مصدر واحد في `pyproject.toml`.

## SQLite

SQLAlchemy Core 2 مع `NullPool`، وتفعيل المفاتيح الخارجية في كل اتصال، و`BEGIN`
صريح لجعل المعاملات وDDL قابلة للتراجع أيضًا على Python 3.11. المخطط الحالي نسخة 4؛
ترقية النسخ 1 و2 و3 مدعومة عند فتح المشروع مع نسخة SQLite backup أولًا.
تُرفض النسخ غير المعروفة ولا يعاد تهيئة قاعدة موجودة.

الجداول الحالية: `schema_version`, `projects`, `units`, `translations`,
`translation_revisions`, `source_files`, `game_imports`, `unit_discovery`, `jobs`,
`job_items`, `providers`, `tm_entries`, `unit_reviews`, `review_revisions`,
`translation_alternatives`, `template_snapshots`, `exports`.
تحفظ المهمة نسخة القاموس، دون محرر مصطلحات مستقل.
جداول `glossary_terms`, `validation_issues` ستضاف بترحيلات مستقلة
عند تنفيذ الميزات التي تستهلكها؛ لا تُنشأ مخططات تخمينية لكل المراحل في التأسيس.

عقد المصدر الكامل، بما فيه `source_text`, `old`, `renpy_identifier`, محفوظ في JSON
ثابت داخل `units.source_data`. مفتاح فريد للمشروع + المسار + النوع + معرّف المحرك
الحقيقي، أو رقم السطر الدقيق حين يجهل المعرف. لا يُستخدم نص العبارة نفسه للدمج.
توسعة حالات وجود مواضع متعددة في السطر نفسه مسؤولية مرحلة parser قبل استيرادها.
لا يُنشأ أي معرّف Ren'Py. SHA-256 يشمل بيانات المصدر والسياق واللغات، ويستثني
معرّفات التطبيق وحالة الترجمة ونصها.

المصدر مجمد في Pydantic، ويُعاد التحقق منه عند الإدخال، ويحظر SQLite تحديث صف
مصدر موجود. الترجمة ومراجعتها تكتبان في معاملة واحدة، مع حفظ كل نسخة جديدة في
`translation_revisions`. تحظر طبقة المستودع وSQLite استبدال الترجمة المعتمدة أو حذفها.
لا توجد واجهة مراجعة كاملة بعد، ومداخل حفظ الترجمات منخفضة المستوى مخصصة لتأسيس
التخزين واختباره. لا تقبل الحالة `validated` قبل وجود المدقق الحقيقي.

## الاكتشاف والاستيراد

`discovery/inventory.py` يجرد الملفات ذات الصلة، ويحفظ بصمات البايتات للمصادر النصية،
ويرفض الروابط وjunctions ويقيد حجم النصوص وعدد المدخلات والوقت. الفهرسة العادية لا تفك
RPA/RPYC؛ أضافت المرحلة 6 مسار Packed مستقلًا بقراءة بيانات خاملة موثقة أدناه.
يقرأ `version_detector.py` أدلة محددة من ملفات المحرك
والسجل، ويعلن التعارض أو عدم المعرفة؛ `config.version` واسم المجلد ليسا دليل إصدار.

`rpy_parser.py` قارئ محافظ حسب سياق label/menu/screen، مع فصل التعليقات والسلاسل
والأسطر المنطقية. تفسير string literal محدود، و`ast.literal_eval` يستخدم فقط لسلسلة
ثابتة محددة داخل تعليمة screen، ولا يُستخدم eval/exec أو استيراد شيفرة لعبة.
`translation_parser.py` يقرأ الأصل من التعليق أو `old`، لا من النص المترجم، ويحتفظ
بالمعرّف حرفيًا. البيانات المتعارضة أو غير المدعومة تضاف إلى التقرير صراحة.

`GameImportService` في `extraction/scanner.py` الخدمة المشتركة للواجهة وCLI. تفضل
القوالب العربية الموجودة أو المولدة. تطابق النص والشخصية والسطر عند توفر المصدر؛
الاختلاف مع تعليمة معروفة يستبعد القالب القديم، وتعذر القراءة يبقى واضحًا كقالب غير
متحقق. النصوص الأخرى تعرض دون معرّف مخمّن. كتل strings تشترك في مفتاح old؛ تختلف
السلاسل ذات الوسم السياقي مثل `{#menu}`، ولا تدمج الحوارات لمجرد تطابق العبارة.

للوحدات الجديدة يحدد `source_location` عنوانًا داخليًا مستمدًا من معرّف القالب وموقع
التعليمة، أو مفتاح old الرسمي، أو موضع المصدر غير المتحقق. هذا ليس معرّف Ren'Py.
يضم `location_key` بصمة المصدر لتسجيل نسخة جديدة عند تغيره، مع إبقاء السجل القديم
وترجمته. تحدد `unit_discovery.active` الوحدات الحالية؛ لا تحذف الإصدارات السابقة.
تحتفظ بصمات المرحلة 0 بخوارزميتها الأصلية، والحقول الاختيارية الجديدة لا تبطلها.
تستثني بصمة الوحدات الجديدة الثقة المشتقة؛ يمكن أن تتحسن في بيانات provenance
دون نسخ المصدر أو مسح ترجمة معتمدة. يحتفظ `source_literal` بتمثيل النص في القالب.

حفظ جرد الملفات والوحدات وبيانات المصدر والترجمات الموجودة يتم في معاملة واحدة.
يعاد فحص الجرد قبل الحفظ لرصد التعديل المتزامن. SQLite مصدر الحقيقة، و`inventory.json`
و`project.yaml` نسختان وصفيتان تكتبان باستبدال ملف مؤقت بعد نجاح المعاملة.

## سياسة SDK في المرحلة 1

أمر translate الرسمي قد ينفذ init Python. لذلك لا يشغّل RAT مشروع المستخدم كما هو:
يتحقق من قائمة تعليمات تصريحية محدودة، ويرفض Python والمصدر الناقص والوحدات المجمعة
بلا مصدر والأرشيفات، ثم ينسخ النصوص المسموح بها فقط إلى `staging/sdk-<uuid>/game`.
لا تنسخ Python أو bytecode أو media أو قوالب قابلة للتنفيذ. تحفظ نهايات الأسطر CRLF
دون مضاعفتها. يُشغّل Python الخاص بالـSDK الموثوق عبر arguments و`shell=False` ومهلة،
مع إزالة متغيرات بيئة Python الخارجية و`-B` وتوجيه savedir إلى staging.

تُفحص نتيجة --version الفعلية، وتُرفض عائلة إصدار مختلفة إذا عُرف إصدار اللعبة.
إصدار SDK لا يتحول إلى إصدار مزعوم للعبة. لا يكفي exit code: يجب وجود قوالب قابلة
للقراءة. وثقت الحدود ونتائج SDK الفعلية في `phase1.md` و`phase1-verification.md`.

## Mock والحماية

`MockProvider` محاكاة echo حتمية تعيد النص حرفيًا وتصرح بـ`simulated: true`.
تعكس ترتيب الدفعة عمدًا لكشف الاعتماد على ترتيب الرد بدل `unit_id`. اختبار الاتصال
يرجع `status: simulated` ولا يدّعي وصولًا إلى API. لا توجد نماذج أو استخدام رموز مزعوم.

نُفذت وحدات tokenizer/placeholders/tags/masking/restoration/validator في `protection`،
وعقودها في `domain/protection.py`. `ProtectionService` يربطها بوحدات الاستخراج؛
تضاف نتائج مشتقة إلى ImportReport دون إعادة كتابة حقول المصدر أو بصمته. يستثني
التخزين حقل protection من payload؛ يعاد تجهيز الخرائط المؤقتة عند فتح التقرير.
لا يلزم ترحيل SQLite، ولا تنتج وحدات مكررة عند إعادة الفهرسة بسبب الحماية.

المحلل يتتبع حالات الأقواس والاقتباسات، ويستخدم ast.parse لفحص التعبير فقط، دون
تنفيذه. تتضمن الخريطة spans وUUID namespace ورمزًا مستقلًا لكل ظهور. يُفحص اتساق
الخريطة ثم عدد الرموز وترتيبها، ويعاد تحليل النص المستعاد ومقارنة العناصر المحمية
حرفيًا لاكتشاف حقن تراكيب أو تغير معناها عند حدود الهروب. تُرفض النتيجة كاملة عند
فشل أي فحص، مع diagnostics منظمة وبدون تسجيل النصوص.

قرار المرحلة 2 المباشر: الترتيب صارم لكل المتغيرات والوسوم، وإغلاق الوسوم الزوجية
صريح إلزامي حتى حين يسمح المحرك بإغلاق ضمني في نهاية النص. الوسوم المخصصة تتطلب
سجل أسماء وأدوار ساكنًا يمرر إلى Core؛ لا تُحمّل معالجات من اللعبة. تفاصيل النطاق
والحدود في `phase2.md`. لا يدعي هذا المدقق صلاحية قيم الوسوم أو ملف .rpy كامل.

الواجهة تعرض حالة الحماية ومعاينة لصف مختار، وتستعمل تقرير Core فقط. CLI protect
يعرض التحليل المحفوظ دون API. يجرب mock-demo النقل المحمي والاستعادة لعينة مدمجة.
منذ المرحلة 3 توجد ترجمة عبر الموصل المختار، ومنذ المرحلة 4 توجد مراجعة وتصدير.
نجاح الحماية لا يمنح حالة validated عامة أو ضمان توافق بصري داخل اللعبة.

## قرارات المرحلة 3

TranslationManager في `translation/orchestrator.py` ينسق حماية المصدر والسياق،
وقفل القاموس، وتقدير الدفعات، وربط نتائج JSON بالمعرفات، ثم الاستعادة والتحقق والحفظ.
لا تعتمد المطابقة ترتيب الرد. تُقسم دفعة JSON غير الصالحة إلى أجزاء أصغر؛ تُرفض
نتيجة فقدت رمزًا ولا تصبح ترجمة مقبولة. الاعتماد اليدوي والتصدير ضمن المرحلة 4 أدناه.

الموصلات ترث BaseTranslationProvider، وتبقى قابلة للفحص بـTranslationProvider.
OpenAI/DeepSeek/OpenRouter/Custom تشترك في طبقة SDK الرسمية مع ملفات تعريف مستقلة،
وGemini عبر google-genai. تستخدم الخدمات موديلًا من المستخدم أو قائمة API؛ لا توجد
أسماء ثابتة. لا يوجد fallback إلى مزود آخر، وتُعطل retries الداخلية للـSDK.

Google Translate يستخدم deep-translator غير الرسمي في عملية فرعية محدودة المهلة.
تحفظ علامات النقل محليًا وتترجم المقاطع العادية بينها؛ لا يدعم prompt سياق LLM.
قتل العامل وانتظاره عند المهلة يمنع ترك thread شبكة معلق. العناوين والمفاتيح لا
تُمرر في argv؛ مسار Google لا يستعمل مفتاحًا، ومدخلاته المؤقتة تنظف بعد انتهاء العامل.

الحفظ لكل دفعة معاملة تجمع translation/revision/TM/job_item. تجهز خرائط النقل
وتحفظ قبل الطلب. قفل OS لكل مشروع يمنع عمليتين من تشغيل محركين عليه في الوقت نفسه؛
تنتهي ملكيته عند موت العملية. تتحول in_progress إلى pending عند استئناف مالك جديد.
Pause/Stop ينتظران الجاري ويحفظانه، وتظل الدفعة غير المحفوظة قابلة لإعادة الإرسال
بعد الانقطاع؛ لا يدعي النظام منع تكرار فوترة الخدمة في هذه الحالة.

مفتاح TM يشمل النص والنوع واللغات والسياق والأسلوب والقاموس والمزود والموديل
والعنوان والمشروع. تُراجع البنية قبل الاستعمال، وتُوحّد الطلبات المتطابقة. نتيجة Mock
لا تُستخدم لمزود حقيقي، لكن يمكن استبدال محاكاة غير معتمدة بمهمة حقيقية مع حفظ revision.
الترجمة المعتمدة لا تتغير عند الاستئناف أو تغيير المزود.

SecretStore يختار WinVaultKeyring صراحة على Windows، ويرفض مخازن plaintext أو
backends غير المعروفة دون fallback. تقيد ProviderConfig العنوان وتمنع أسرار URL؛
تغيير endpoint يحتاج هوية جديدة حتى لا ينتقل مفتاح قديم إليه. logs تحتفظ بفئات
أخطاء مسموح بها فقط، لا رسائل SDK أو headers أو نصوص اللعبة أو المفاتيح.

صفحتا المزود والتقدم تستخدمان Core عبر TaskWorker/QThread؛ لا HTTP داخل UI.
حدود التزامن وRPM وميزانية tokens خاصة بالمهمة؛ Google قد يجري طلبات متعددة
للمقاطع داخل الدفعة. تفاصيل العقود والقيود التشغيلية في `phase3.md`.

## قرارات المرحلة 4

`domain/review.py` يعرّف عقود المحرر وQA والتقرير، و`review.py` ينظم عمليات المراجع.
`translation/quality.py` يضيف فحوص المحتوى فوق حماية Phase 2؛ لا يتجاوزها.
واجهتا review/export تستخدمان Core، والطلبات والتصدير على QThread. نموذج الجدول
يدعم حفظ الخلية مباشرة ومربع التحرير يحفظ بعد 500ms وقبل الانتقال والإغلاق.

لا نزيل trigger حماية الصفوف المعتمدة القديمة: `unit_reviews` يمثل قرار المراجع
الحالي، و`review_revisions` تاريخ إضافي لا يمس المصدر أو الاعتماد السابق. Reject
صريح يسمح بمسودة لاحقة، وتحمي etag ومعاملة واحدة عمليات المجموعات من الحفظ المتعارض.
حالة Locked علم مستقل، وSkip استبعاد مستقل. مهمة Phase 3 عادية تتجاوز كل مسودة
حررها المراجع وكذلك المقفل والمستبعد؛ تفحص ذلك عند الإنشاء وقبل إرسال الطلب وعند الحفظ.

طلبات البدائل تحفظ `translation_alternatives` مرتبطة بالمهمة وبصمة المصدر ولا
تكتب الترجمات الحالية أو TM. تعطيل TM والتجميع المتطابق مقصود لطلب بديل جديد.
تطبيق بديل يحفظ مسودة عبر ReviewService ويتطلب Reject/Unlock عند الحاجة.
تظل جداول المرحلة 3 سجلاتها الأصلية؛ المحرر وExport يقرآن overlay المراجع بوصفه
الحالة الحالية، وجدول الفهرسة القديم يعرض معلومات المصدر وحالة مرحلة الاستيراد.

`exporters` ينفذ التصدير في مجلد مستقل، مع قفل المشروع ضد مهام الترجمة ولقطة
QA/مراجعات ثابتة للعملية. `TemplateCatalog` يتحقق من بصمات المصدر قبل أول لقطة
ويحفظها في SQLite؛ اللقطة مرتبطة باستيراد دقيق. `RenPyWriter` لا يولد IDs ولا
ينفذ لعبة، ويعيد تحليل الناتج للمطابقة. ترميز الحوار مختلف عن Python literals
في old/new، وفق SDK الفعلي. rename نهائي ينشر مجلد تصدير مكتمل الكتابة.

`BackupManager` يستخدم SQLite backup وSHA256 للمشروع فقط. لا ميزة تثبيت أو استعادة
لأصول اللعبة. المسارات ترفض الاجتياز والروابط وأسماء Windows المحجوزة وتداخل المشروع
مع أصل اللعبة. [phase4.md](phase4.md) يبين حدود الصيغ وQA والتصدير بالتفصيل.

## قرارات المرحلة 5

عقود `domain/arabic.py` تمتد بإعدادات runtime داخل `ArabicSettings` الحالية؛
الافتراضي معطّل، فتظل مشاريع المراحل السابقة قابلة للفتح والتصدير. لا ترحيل
SQLite جديد؛ تظل v4. تُحفظ إعدادات المشروع في YAML باستبدال ذري تحت قفل المشروع.

`arabic/fonts.py` يفحص cmap وGSUB/GPOS وقيود fsType بوساطة fontTools دون Qt،
مع حد 16MiB لكل TTF/OTF. مسار Arabic لا يكتفي بقيام Qt بتحميل الخط. الخطوط
المخصصة تحتاج تصريح إعادة توزيع وملف ترخيص، وتُنقل نسخ ذات بصمة إلى runtime/fonts
في المشروع. النسخة الاحتياطية تشمل هذه الملفات وتراخيصها. لا يُعدل ملف الخط.
Amiri الأصلي ونص OFL ضمن resources بالحزمة ليعمل المصدر وwheel وEXE دون تنزيل.
`assets/fonts/README.md` يوضح المصدر؛ هذه إضافة مورد توزيع إلى البنية الحالية.

FontGroup يوجه محارف الخط العربي إلى وجه يغطي العربية الأساسية كاملة، ثم يخصص
باقي المحارف وفق الأولوية والتغطية. لا يُجزّأ خط الكلمة العربية إلى fallback حرفي
من وجوه ناقصة. أسماء ملفات التصدير تستخدم 16 خانة من البصمة لتقليل طول مسارات
Windows/SDL، وتتحقق من التصادم وتحتفظ بـSHA256 الكامل في manifest؛ ليست IDs للترجمة.

`rtl_profiles.py` يفصل القدرات المعروفة عن التحقق الحي. 8.2 يضيف HarfBuzz و8.4
يضيف reading_order ويصلح مشكلة bidi في سلسلة 8.3.7؛ المحجوب لا يُعالَج بقلب النص.
التحقق الحي هنا لـ8.5.3 فقط. إصدار SDK المستخدم في الاستخراج لا يصبح إصدار اللعبة؛
تُقبل بيانات اللعبة أو تأكيد يدوي صريح عند غيابها، مع منع التعارض وحارس إصدار داخل rpy.

`StyleGenerator` يولد arabic_runtime.rpy مستقلًا في tl/arabic. يحافظ على Unicode
المنطقي ولا يغير ترجمات أو محميات Phase 2. تُطبق الأنماط عبر build_styles_callbacks،
لأن language_callbacks وحده يسبق إعادة تطبيق أنماط GUI المؤجلة، وقد تلغيه اللعبة.
لا تطبق الطبقة قبل أن يأخذ Ren’Py لقطة الأنماط الأصلية، فتظل استعادتها ممكنة. تتفعل
فقط للغة arabic، ويعيد تغيير اللغة أو set_enabled إعادة بناء الأنماط. sentinel
rat_runtime.disabled يعطلها عند بدء التشغيل؛ زر التعطيل يحفظ اختيارًا في persistent.
دعم callback مبني على SDK الفعلي؛ تبقى الإصدارات الأخرى غير مختبرة حيًا.

لا نعيد تعريف الشاشات الأصلية أو نعكس صفوف الأزرار تلقائيًا. أنماط الحوار والأسماء
والخيارات والسجل والتفضيلات ومحاذاة النصوص القياسية تُولّد؛ الأنماط أو وسوم font
المخصصة قد تتجاوزها وتحتاج فحص اللعبة. تُرصد كتل أنماط عربية سابقة وتعارض اسم الملف
والـnamespace، دون تنفيذ Python مستخرج. فشل إعداد Runtime مطلوب يمنع إخراج الترجمات.

UI يستدعي Core للفحص والحفظ وإنشاء المشروع التجريبي على QThread؛ Preview HTML
مقيد ومولّد من tokenizer، ولا يقيّم placeholders. Qt ليس بديلًا عن اختبار Ren’Py.
المشروع التجريبي كود أصلي مؤلف لـRAT، وهو وحده الذي يشغله اختبار SDK للرسم وlint،
دون تشغيل ألعاب المستخدم. CLI arabic يستخدم Core نفسه. [phase5.md](phase5.md)
يشرح التوافق والتعطيل وحدود الخطوط والتجربة.

## مراجع تقنية

قرار المرحلة 6: `domain/packed.py` يحمل عقود الخيارات والـmanifest والتعارض والتوافق،
و`extraction/packed_manager.py` ينظم دورة الاستخراج والتحليل والاستيراد تحت قفل المشروع.
`rpa_adapter.py` و`rpyc_adapter.py` يفصلان تفاصيل الحاويات؛ عقد DecompilerAdapter يسمح
بمحولات لاحقة دون ربط UI أو Discovery بأداة خارجية. المحول الحالي محدود وخامل،
ولا يشغل unrpyc أو أي كود لعبة. `security/pickle_data.py` يفسر بيانات pickle تحت حدود
بدل unpickle التنفيذي؛ لا imports أو hooks للأصناف المستخرجة.

`packed_workspace.py` يملك النسخ المرحلية وحل التعارضات وبصمات الملفات وحذف التشغيل
المحدد فقط. الإدخال من داخل مشروع RAT يحتاج manifest مملوكًا وview مطابق البصمات؛
لا يُرفع حارس تداخل المجلدات عمومًا. `PackedProvenance` في عقد ImportReport يفرق بين
جذر اللعبة الأصلي وجذر القراءة المرحلي، فتستخدم حواجز التصدير والنسخ والخطوط الأصل.
تبقى SQLite v4 والعقود السابقة متوافقة، وتُحفظ لقطة القوالب الموجودة قبل التنظيف.
معرف `Say id` الحقيقي يُحفظ بعد تحليل RPC2 slot 2، ولا يُولد معرف من اسم الملف أو النص.
الاستعادة الجزئية لا تُشغل عبر SDK؛ المصدر التصريحي الكامل الموثق فقط يمر بالحارس السابق.
واجهة Packed وأوامر CLI يستدعيان الخدمة نفسها، ولا يحتويان منطق فك الملفات.
التفاصيل والحدود في [phase6.md](phase6.md). لا تنفيذ لإضافات المزودات أو مثبت المرحلة 7
ضمن هذا الطلب المباشر المحدد لدعم الملفات المجمعة.

- [Pydantic models](https://docs.pydantic.dev/latest/concepts/models/)
- [SQLAlchemy SQLite، المعاملات والمفاتيح الخارجية](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html)
- [Qt QApplication](https://doc.qt.io/qtforpython-6/PySide6/QtWidgets/QApplication.html)

## تشغيل Windows المستقل

`scripts/rat_desktop.py` نقطة دخول تغليف مستقلة تستدعي `rat.app.main` في التشغيل
العادي. `scripts/RAT.spec` يضم Python وQt وSQLite والمكتبات المطلوبة في `dist/RAT.exe`
بنمط onefile وواجهة دون نافذة أوامر. أُدرج موصل SQLite الديناميكي صراحة في hiddenimports.
لا يُثبّت EXE حزمًا ولا ينزّل شيفرة عند تشغيله.

يجمع `scripts/collect_licenses.py` إشعارات الاعتماديات ونص رخصة Python ونصوص Qt
المحفوظة في `assets/licenses/`، ثم يضمها البناء كمورد داخلي. تعرضها قائمة المساعدة
عبر `ui/licenses_dialog.py` دون حاجة لملف مجاور للـEXE.

الوسيط الداخلي `--self-test` يشغّل `desktop_checks.py` فقط عند طلبه صراحة، ويفتح
نافذة Qt ويختبر إنشاء مشروع وإغلاقه وإعادة فتحه وموصل Mock داخل مجلد الاختبار.
لا يؤثر في التشغيل العادي أو ملفات المستخدم. يتوقف البناء قبل التغليف عند فشل
pytest أو ruff؛ تتوفر نقطة بناء Python مباشرة لتجنب تغيير سياسة PowerShell.


## Phase 7 release decisions

Existing services and SQLite schema v4 are retained. Windows is distributed as a
onefile GUI EXE with an explicit hidden Windows vault/SQLite/fontTools dependency
set. The release builder runs an isolated copied-EXE smoke and binds packaging to
its SHA256 and application version. Inno Setup installs per user under LocalAppData
Programs without elevation; uninstall does not delete settings, projects or vault
entries. Portable uses the same user directories and is not a self-contained data vault.

Lifecycle logs are rotating JSON with allowlisted events/version only. Unhandled
exceptions record a safe event without exception messages or traceback locals.
Diagnostic reports are built from a fixed set of versions/counts, not by redacting
arbitrary logs: no source text, credentials, environment, headers or paths are copied.

BackupManager seeds verified template snapshots and uses SQLite backup, then hashes
metadata/fonts. Restore verifies a detached backup into a new sibling staging folder,
checks the database, and publishes only a valid project by rename. Identity, immutable
source rows and checkpoint data stay unchanged. Older backups without cached templates
may still need their original template files. Failed staging is retained for inspection.

InstallationService accepts a completed export tied to the current source inventory.
It only creates a new independent game copy, rejecting links, overlaps and changed
source hashes. Packed imports remain export-only because their original archive
identity needs separate installation validation. The project checkpoint and all patch
replacement backups exist before patch writes. A durable journal makes an interrupted
prepared installation restorable; source-game files are never restoration targets.
Ren'Py-generated RPYC siblings are invalidated/restored with their corresponding RPY.
Manual changes to installed RPY block rollback. Games must be closed during these actions.

No automatic update, new translation provider, schema redesign or Phase 8 work is added.
