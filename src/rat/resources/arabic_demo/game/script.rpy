# Original RAT integration fixture. This is trusted test code authored for RAT.
init python:
    gui.init(1280, 720)

define config.name = "RAT Arabic Runtime Demo"
define config.version = "1.0"
define config.save_directory = None
define config.rtl = False
default player_name = "Alex"
define e = Character("ليلى / Layla")

style say_dialogue:
    font "DejaVuSans.ttf"
    size 30
    color "#ffffff"
    shaper "freetype"
style say_label is say_dialogue
style choice_button_text is say_dialogue
style history_text is say_dialogue
style history_name_text is say_dialogue
style pref_label_text is say_dialogue
style pref_button_text is say_dialogue
style pref_text is say_dialogue

screen say(who, what):
    window:
        id "window"
        background "#142238"
        yalign 1.0
        xfill True
        ysize 200
        padding (40, 18)
        vbox:
            xfill True
            if who:
                text who id "who" style "say_label"
            text what id "what" style "say_dialogue"

screen rat_runtime_panels():
    frame:
        background "#18273d"
        xalign 0.5
        ypos 20
        xsize 1200
        padding (24, 16)
        vbox:
            spacing 12
            text "اختبار العربية / Arabic Runtime — 2026" style "pref_label_text"
            text "السجل: أنهى Alex المرحلة 12 بنجاح — النتيجة ٣٤٥" style "history_text"
            text "التفضيلات / Preferences: سرعة النص 42 — مستوى الصوت ٧٥" style "pref_text"
            textbutton "الخيار الأول: ابدأ Chapter 2 — 123" text_style "choice_button_text" action NullAction()
            hbox:
                spacing 20
                textbutton "تعطيل طبقة RAT" action Function(rat_arabic_runtime.set_enabled, False)
                textbutton "تفعيل طبقة RAT" action Function(rat_arabic_runtime.set_enabled, True)
                textbutton "الوضع السابق" action Language(None)
                textbutton "العربية" action Language("arabic")

label main_menu:
    return

label start:
    scene expression Solid("#0b1220")
    python:
        import os
        import json
        mixed = "مرحبًا [player_name]! {b}المستوى 12{/b} — Build 42 / 123 — النتيجة ٣٤٥"
        runtime = renpy.store.rat_arabic_runtime
        original_font = style.say_dialogue.font
        original_size = style.say_dialogue.size
        original_rtl = config.rtl
        renpy.change_language("arabic", force=True, rebuild=True)
        if os.environ.get("RAT_RUNTIME_AUTOTEST"):
            disabled = os.environ.get("RAT_RUNTIME_EXPECT_DISABLED") == "1"
            assert runtime.active != disabled
            if not disabled:
                assert style.say_dialogue.shaper == "harfbuzz", repr(style.say_dialogue.shaper)
                assert style.say_dialogue.reading_order == "wrtl", repr(style.say_dialogue.reading_order)
                assert config.rtl is True
                for name in ("say_label", "choice_button_text", "history_text", "pref_text"):
                    assert getattr(style, name).shaper == "harfbuzz"
            assert "[player_name]" in mixed and "{b}" in mixed and "{/b}" in mixed
            rendered = renpy.substitute(mixed)
            assert "Alex" in rendered and "Build 42 / 123" in rendered and "٣٤٥" in rendered
            renpy.show_screen("rat_runtime_panels")
            renpy.say(e, mixed, interact=False)
            renpy.pause(0.4)
            image_name = "arabic-disabled.png" if disabled else "arabic-native.png"
            renpy.screenshot(os.path.join(config.basedir, image_name))
            if not disabled:
                runtime.set_enabled(False)
                assert style.say_dialogue.font == original_font
                assert style.say_dialogue.size == original_size
                assert config.rtl == original_rtl and not runtime.active
                runtime.set_enabled(True)
                assert runtime.active and style.say_dialogue.shaper == "harfbuzz"
            renpy.change_language(None, force=True, rebuild=True)
            assert style.say_dialogue.font == original_font and config.rtl == original_rtl
            with open(os.path.join(config.basedir, "runtime-result.json"), "w") as stream:
                json.dump({"status": "passed", "disabled": disabled,
                    "mixed_text_preserved": True, "styles_restored": True,
                    "version": list(renpy.version_tuple)}, stream)
            renpy.quit()
    show screen rat_runtime_panels
    e "مرحبًا [player_name]! {b}المستوى 12{/b} — Build 42 / 123 — النتيجة ٣٤٥"
    menu:
        "متابعة / Continue 123":
            e "تمت المتابعة بنجاح — النتيجة ٣٤٥"
        "إنهاء / Exit":
            pass
    return
