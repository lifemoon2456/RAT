# المرحلة 5 — Arabic Runtime Integration

دليل المبتدئ في [README، القسم 11](../README.md#arabic-runtime).
التنفيذ مستقل عن المزودات؛ لا API أو تنفيذ Python مستخرج من لعبة أثناء الفحص.

## التوافق

| إصدار المحرك | الملف التشغيلي |
|---|---|
| مجهول أو أدلة متعارضة | حجب تضمين Runtime؛ المعاينة تبقى ممكنة. |
| 7.x أو 8.0/8.1 | غير متحقق؛ يحتاج فرع legacy وتجربة منفصلة. لا preprocessing تلقائي. |
| 8.2–8.3.6 | HarfBuzz وRTL أصليان، دون reading_order. تحذير أنه لم يختبر حيًا هنا. |
| 8.3.7 وما بعدها ضمن سلسلة 8.3 | حجب تحفظي لمشكلة ترتيب المقاطع المختلطة الموثقة. |
| 8.4+ ضمن عائلة 8 | HarfBuzz وreading_order؛ تلقائي = wrtl، أو rtl/ltr حسب الاختيار. |
| 8.5.3.26051504 | الإصدار الذي اجتاز التشغيل والرسم الفعلي في هذه المرحلة. |
| عائلة رئيسية غير معروفة | غير مدعومة حتى التحقق. |

القدرات الأخرى في الجدول ملفات توافق مبنية على التوثيق، وليست نتائج تشغيل حي.
الكشف يقرأ ثوابت وبيانات إصدار من renpy وlog دون import أو eval. أضيف دعم
vc_version.json إلى كشف المرحلة 1؛ SDK الاستخراج لا يصبح دليلًا على محرك اللعبة.
عند غياب الدليل يسمح بإصدار يدوي مع إقرار صريح، ويمنع تعارضه مع إصدار مكتشف.
الملف المولد يفحص الإصدار الفعلي عند التفعيل ويرفض اختلافه عن الهدف المسجل.
لا يُحدّث محرك اللعبة أو يستبدل مكتباته.

التوثيق الرسمي يحدد [HarfBuzz منذ 8.2 وإصلاح bidi في 8.4](https://www.renpy.org/doc/html/changelog.html)،
ويشرح [shaper وreading_order](https://www.renpy.org/doc/html/style_properties.html).
المرجع المتاح أثناء العمل كان 8.5.4؛ اختُبرت التفاصيل أيضًا على SDK المحلي 8.5.3.

## الخطوط

FontManager يستخدم fontTools لقراءة cmap، واستبعاد glyph صفر، وفحص وجود GSUB/GPOS
والحروف العربية الأساسية وعلامات التشكيل والأرقام العربية وعلامات الترقيم.
يتحقق من قيود embedding المعلنة في OS/2.fsType. هذا لا يمنح ترخيص توزيع ولا يضمن
كل ميزات الخط؛ لذلك تحتاج الخطوط المخصصة إقرار حق توزيع ونص ترخيص UTF-8 صالحًا.
يدعم TTF/OTF وحدًا قدره 16MiB وخمسة خطوط إجمالًا، ولا يغيّرها أو يقلصها.

Amiri Regular المرفق يغطي المحارف الأساسية والتشكيل واللاتينية والأرقام، ويشمل
نص SIL OFL 1.1 وحقوق The Amiri Project Authors. المصدر
[Google Fonts / Amiri](https://github.com/google/fonts/tree/main/ofl/amiri).
بصمة الملف الأصلي SHA256:
`ab391c4147d054c48976e98322ad0eefe1427aa0e0502a12a4c75d80a70cfcd7`.

تختار FontGroup وجهًا واحدًا كامل التغطية للعربية، ثم تضيف المحارف الأخرى بحسب
أولوية الأساسي والاحتياطي. هذا يمنع توزيع حروف الكلمة المتصلة على وجوه عربية
ناقصة. الترخيص والملف ينسخان إلى runtime/fonts في مشروع RAT عند الحفظ، ويشملهما
BackupManager. لا يعتمد التصدير على بقاء الملف الذي اختاره المستخدم خارج المشروع.

يُفحص غياب glyph من النصوص الظاهرة قبل إخراجها؛ تُستثنى شيفرة الوسوم والـplaceholders
لأنها ليست محارف ستعرض حرفيًا. قيم المتغيرات المستقبلية وأسماء اللاعبين تحتاج
تغطية فعلية وقت التشغيل وقد تحتاج fallback إضافيًا. وسوم font والأنماط المخصصة
قد تختار خطوطًا أخرى؛ لا يبدّلها RAT بالقوة أو يزيلها.

## الملف التشغيلي والرجوع

المخرجات الإضافية عند التفعيل:

```text
game/tl/arabic/arabic_runtime.rpy
game/tl/arabic/fonts/<font-hash-prefix>.ttf
game/tl/arabic/fonts/<font-hash-prefix>.license.txt
arabic-runtime.json
```

لا يتغير source_text أو old أو renpy_identifier أو نص الترجمة. لا عكس سلاسل، ولا
arabic_reshaper أو python-bidi. Ren'Py ينفذ interpolation والوسوم وHarfBuzz وبقية
ترتيب Unicode بنفسه. إعدادات الحوار والأسماء والخيارات وHistory وPreferences
تطبق على أنماط Ren'Py القياسية، مع حجم مستقل ومحاذاة اختيارية. لا تعديل gui.rpy
أو إعادة تعريف شاشة أصلية أو إعادة ترتيب كل أزرار واجهة مخصصة تلقائيًا.

تطبيق الأنماط في build_styles_callbacks مهم: callback اللغة وحده يأتي قبل
أنماط GUI المؤجلة ويمكن أن تلغيه. تُترك لقطة الأنماط الأصلية في المحرك سليمة،
ويشمل التحقق الفعلي حفظ الأصل والتعطيل وإعادة التفعيل وتغيير اللغة. لا تنشط
الطبقة خارج اللغة arabic. تُرصد تعارضات اسم الملف والـnamespace والكتل العربية
الموجودة دون تشغيلها. تبقى الاختلافات المخصصة بحاجة إلى فحص على نسخة مخولة.

- تعطيل الإخراج: احفظ runtime.enabled=false ثم صدّر حزمة جديدة.
- تعطيل نسخة اختبار موجودة: أنشئ game/tl/arabic/rat_runtime.disabled ثم أعد التشغيل.
- تعطيل حي داخل العينة: زر يستدعي rat_arabic_runtime.set_enabled(False)، مع إعادة
  بناء الأنماط وحفظ الاختيار في persistent. True يعيد التفعيل، ما لم يوجد sentinel.
- حذف sentinel مع إلغاء التعطيل المحفوظ يعيد الطبقة؛ الترجمات لا تُمسح.

نسخ ملفات إصدار جديد فوق حزمة قديمة لا يحذف ملفات Runtime المتروكة تلقائيًا؛
استخدم sentinel أو نسخة اختبار نظيفة. لا توجد ميزة تثبيت أو إزالة ملفات لعبة
تلقائية في هذه المرحلة. التعطيل يعيد أنماط المحرك السابقة، لا لغة النص الأصلي.

## المعاينة والعينة

Qt preview يولد HTML محدودًا عبر tokenizer الحالي. يدعم أمثلة b/i/u/s/color
ويستبدل عددًا محدودًا من placeholders بقيم تجريبية ثابتة، دون eval للتعبيرات.
المعاينة تقريبية؛ لا تقيس جميع وسوم Ren'Py أو شكل اللعبة أو نوافذها.

زر المشروع التجريبي ينسخ موارد RAT الأصلية والخطوط المرخصة إلى staging/arabic-demo-...
ويستهدف SDK المختار. لا ينسخ لعبة المستخدم ولا يشغلها أو يشغل SDK بمجرد الضغط.
العينة تعرض حوارًا وشخصية وخيارًا ونماذج نصوص History/Preferences وتبديل اللغة
والطبقة؛ ليست كل شاشات GUI الأصلية لأي لعبة.

يمكن تشغيلها من Launcher، أو للمطور على Windows:

```powershell
$sdkPath = 'D:\B\777\LC\renpy-8.5.3-sdk'
$demoPath = '<المسار الذي عرضه RAT>'
& "$sdkPath\lib\py3-windows-x86_64\python.exe" "$sdkPath\renpy.py" $demoPath lint
& "$sdkPath\lib\py3-windows-x86_64\python.exe" "$sdkPath\renpy.py" $demoPath run
```

اختبارات SDK تشغل هذه العينة المؤلفة محليًا فقط، وتتحقق من الرسم والوسوم
والاستبدال ومن الرجوع. اختبار لعبة مستخدم تلقائيًا أثناء التحليل غير متاح.

## CLI والإعدادات

```powershell
.\.venv\Scripts\rat.exe arabic --project '<project>'
.\.venv\Scripts\rat.exe arabic --project '<project>' --disable
.\.venv\Scripts\rat.exe arabic --project '<project>' --demo-sdk '<sdk>'
.\.venv\Scripts\rat.exe arabic --project '<project>' --settings 'arabic.yaml'
```

مثال arabic.yaml؛ هو محتوى ArabicSettings دون المفتاح الخارجي arabic:

```yaml
layout_direction: auto
runtime:
  enabled: true
  primary_font:
    path: builtin:amiri
  sizes:
    dialogue: 32
    names: 32
    choices: 30
    history: 28
    preferences: 28
```

يستخدم هذا المثال الإصدار المكتشف من اللعبة. لا يُضاف target_version يدويًا
إلا بعد التحقق، مع target_version_confirmed: true. فشل الإعدادات يبقي YAML السابق؛
الافتراضي معطّل في المشاريع القديمة. نتائج التنفيذ في [phase5-verification.md](phase5-verification.md).
