"""Backend wording in English, Tamil and Hindi (Time Agent replies and the assistant).

English is the reference text (tests and evidence rely on it). Tamil and Hindi are translations to be reviewed by a native
speaker before production; technical values (activity codes, names, dates) are never translated.
"""
from __future__ import annotations

import re

LANGS = ("en", "ta", "hi")

MESSAGES: dict[str, dict[str, str]] = {
    "q_activity": {
        "en": "Which activity was it? Please resend the message with the line, equipment or area (for example 'Line 1203 erection started today').",
        "ta": "எந்த வேலை? லைன், உபகரணம் அல்லது பகுதியுடன் செய்தியை மீண்டும் அனுப்பவும் (உதாரணம்: 'Line 1203 erection இன்று தொடங்கியது').",
        "hi": "कौन-सा काम? कृपया लाइन, उपकरण या क्षेत्र के साथ संदेश फिर से भेजें (उदाहरण: 'Line 1203 erection आज शुरू हुआ')।"},
    "q_event_multi": {
        "en": "The message reports more than one status; please send one message per status.",
        "ta": "செய்தியில் ஒன்றுக்கு மேற்பட்ட நிலை உள்ளது; ஒவ்வொரு நிலைக்கும் தனிச் செய்தி அனுப்பவும்.",
        "hi": "संदेश में एक से ज़्यादा स्थिति है; हर स्थिति के लिए अलग संदेश भेजें।"},
    "q_event_none": {
        "en": "Did the work start, finish or is it in progress? Please resend the message with that word.",
        "ta": "வேலை தொடங்கியதா, முடிந்ததா, அல்லது நடைபெறுகிறதா? அந்தச் சொல்லுடன் மீண்டும் அனுப்பவும்.",
        "hi": "काम शुरू हुआ, पूरा हुआ या चल रहा है? कृपया वह शब्द जोड़कर फिर से भेजें।"},
    "q_date_multi": {
        "en": "The message mentions more than one date ({dates}); please resend it with one date.",
        "ta": "செய்தியில் ஒன்றுக்கு மேற்பட்ட தேதிகள் உள்ளன ({dates}); ஒரு தேதியுடன் மீண்டும் அனுப்பவும்.",
        "hi": "संदेश में एक से ज़्यादा तारीख़ें हैं ({dates}); एक तारीख़ के साथ फिर से भेजें।"},
    "q_date_none": {
        "en": "What date was it {verb}? (for example 'today', 'yesterday' or 2026-09-24)",
        "ta": "எந்தத் தேதியில் {verb}? (உதாரணம்: 'இன்று', 'நேற்று' அல்லது 2026-09-24)",
        "hi": "यह किस तारीख़ को {verb}? (उदाहरण: 'आज', 'कल' या 2026-09-24)"},
    "verb_start": {"en": "started", "ta": "தொடங்கியது", "hi": "शुरू हुआ"},
    "verb_finish": {"en": "completed", "ta": "முடிந்தது", "hi": "पूरा हुआ"},
    "verb_other": {"en": "done", "ta": "நடந்தது", "hi": "हुआ"},
    "q_discipline": {
        "en": "Which discipline is this (civil, piping, electrical, instrumentation, hse)?",
        "ta": "இது எந்தத் துறை (civil, piping, electrical, instrumentation, hse)?",
        "hi": "यह कौन-सा विभाग है (civil, piping, electrical, instrumentation, hse)?"},
    "rec_matched": {
        "en": "Recorded and linked to {code} ({name}).",
        "ta": "பதிவு செய்யப்பட்டு {code} ({name}) உடன் இணைக்கப்பட்டது.",
        "hi": "दर्ज किया गया और {code} ({name}) से जोड़ा गया।"},
    "rec_review": {
        "en": "Recorded, but planner review is required.",
        "ta": "பதிவு செய்யப்பட்டது; திட்டமிடுபவரின் சரிபார்ப்பு தேவை.",
        "hi": "दर्ज किया गया, लेकिन प्लानर की समीक्षा ज़रूरी है।"},
    "rec_unmatched": {
        "en": "Recorded, but it could not be safely linked to an existing activity.",
        "ta": "பதிவு செய்யப்பட்டது, ஆனால் ஏற்கனவே உள்ள எந்த வேலையுடனும் பாதுகாப்பாக இணைக்க முடியவில்லை.",
        "hi": "दर्ज किया गया, लेकिन इसे किसी मौजूदा काम से सुरक्षित रूप से नहीं जोड़ा जा सका।"},
    "not_scope": {
        "en": "Not recorded: this key may only log {allowed} progress (the message reports {got}).",
        "ta": "பதிவு செய்யப்படவில்லை: இந்தச் சாவி {allowed} முன்னேற்றத்தை மட்டுமே பதிவு செய்ய முடியும் (செய்தி {got} பற்றியது).",
        "hi": "दर्ज नहीं किया गया: यह कुंजी केवल {allowed} प्रगति दर्ज कर सकती है (संदेश {got} के बारे में है)।"},
    "not_valid": {
        "en": "Not recorded: {errors}. Please correct and resend.",
        "ta": "பதிவு செய்யப்படவில்லை: {errors}. திருத்தி மீண்டும் அனுப்பவும்.",
        "hi": "दर्ज नहीं किया गया: {errors}. कृपया सुधारकर फिर से भेजें।"},
    "duplicate": {"en": "Already recorded.", "ta": "ஏற்கனவே பதிவு செய்யப்பட்டது.", "hi": "पहले ही दर्ज है।"},
    "checklist": {
        "en": "{n} {discipline} activities are expected to be active today; {done} already reported.",
        "ta": "இன்று {n} {discipline} வேலைகள் நடைபெற வேண்டும்; {done} ஏற்கனவே பதிவாகியுள்ளன.",
        "hi": "आज {n} {discipline} काम चालू होने चाहिए; {done} पहले ही दर्ज हैं।"},
    "checklist_missing": {"en": " Not reported yet: {items}", "ta": " இன்னும் பதிவாகாதவை: {items}", "hi": " अभी दर्ज नहीं: {items}"},
    # ---- assistant
    "refuse": {
        "en": "I can only help with P2E Bridge, this project's progress, and Oil India Limited (company, results, production, environment, CSR, market and reviews). Please ask about one of those.",
        "ta": "P2E Bridge செயலி, இந்தத் திட்டத்தின் முன்னேற்றம், ஆயில் இந்தியா நிறுவனம் (முடிவுகள், உற்பத்தி, சுற்றுச்சூழல், CSR, சந்தை, மதிப்பாய்வுகள்) பற்றி மட்டுமே என்னால் உதவ முடியும். அவற்றில் ஒன்றைப் பற்றிக் கேளுங்கள்.",
        "hi": "मैं केवल P2E Bridge, इस प्रोजेक्ट की प्रगति और ऑयल इंडिया लिमिटेड (नतीजे, उत्पादन, पर्यावरण, CSR, बाज़ार और समीक्षाएँ) के बारे में मदद कर सकता हूँ। कृपया इनमें से किसी के बारे में पूछें।"},
    "greet": {
        "en": "Hello! Ask me about the app (\"how do I upload a report?\"), the project (\"what delayed piping work?\") or Oil India (\"what is OIL's net zero target?\").",
        "ta": "வணக்கம்! செயலி (\"அறிக்கையை எப்படிப் பதிவேற்றுவது?\"), திட்டம் (\"குழாய் வேலை ஏன் தாமதம்?\") அல்லது ஆயில் இந்தியா (\"OIL-இன் நிகர பூஜ்ஜிய இலக்கு என்ன?\") பற்றிக் கேளுங்கள்.",
        "hi": "नमस्ते! ऐप (\"रिपोर्ट कैसे अपलोड करें?\"), प्रोजेक्ट (\"पाइपिंग काम में देरी क्यों हुई?\") या ऑयल इंडिया (\"OIL का नेट ज़ीरो लक्ष्य क्या है?\") के बारे में पूछें।"},
    "company_none": {
        "en": "I have no verified information on that. I can tell you about: {topics}.",
        "ta": "அதைப் பற்றிச் சரிபார்க்கப்பட்ட தகவல் என்னிடம் இல்லை. இவை பற்றிச் சொல்ல முடியும்: {topics}.",
        "hi": "इस बारे में मेरे पास सत्यापित जानकारी नहीं है। मैं इनके बारे में बता सकता हूँ: {topics}।"},
    "no_records": {"en": "No matching records in the project history.", "ta": "திட்ட வரலாற்றில் பொருந்தும் பதிவுகள் இல்லை.",
                   "hi": "प्रोजेक्ट इतिहास में कोई मेल खाता रिकॉर्ड नहीं।"},
    "in_english": {"en": "", "ta": "(விவரங்கள் ஆங்கிலத்தில்) ", "hi": "(विवरण अंग्रेज़ी में) "},
    "p_duration": {
        "en": "{n} completed activities took {mean} days on average (range {lo}-{hi}) against {plan} days planned, as of {as_of}.",
        "ta": "{n} முடிந்த வேலைகள் சராசரியாக {mean} நாட்கள் எடுத்தன (வரம்பு {lo}-{hi}; திட்டம் {plan} நாட்கள்), {as_of} நிலவரப்படி.",
        "hi": "{n} पूरे हुए काम औसतन {mean} दिन में हुए (सीमा {lo}-{hi}; योजना {plan} दिन), {as_of} तक।"},
    "p_delays": {"en": "{holds} hold reports: {cats}.", "ta": "{holds} நிறுத்த அறிக்கைகள்: {cats}.", "hi": "{holds} रुकावट रिपोर्टें: {cats}।"},
    "p_rate_item": {"en": "{unit}: {per_day} per day", "ta": "{unit}: ஒரு நாளைக்கு {per_day}", "hi": "{unit}: प्रति दिन {per_day}"},
    "p_rate": {"en": "{items}, as of {as_of}.", "ta": "{items}, {as_of} நிலவரப்படி.", "hi": "{items}, {as_of} तक।"},
    "p_late": {"en": "Started late: {s} ({sl}); finished late: {f} ({fl}).", "ta": "தாமதமாகத் தொடங்கியவை: {s} ({sl}); தாமதமாக முடிந்தவை: {f} ({fl}).",
               "hi": "देर से शुरू: {s} ({sl}); देर से पूरे: {f} ({fl})।"},
    "p_count": {"en": "{count} activities ({by_status}).", "ta": "{count} வேலைகள் ({by_status}).", "hi": "{count} काम ({by_status})।"},
    "p_status": {"en": "Status: {items}", "ta": "நிலை: {items}", "hi": "स्थिति: {items}"},
    "p_fresh": {"en": "{silent} activities have no recent report. Last reports: {last}.",
                "ta": "{silent} வேலைகளுக்குச் சமீபத்திய அறிக்கை இல்லை. கடைசி அறிக்கைகள்: {last}.",
                "hi": "{silent} कामों की हाल की रिपोर्ट नहीं है। आख़िरी रिपोर्टें: {last}।"},
    "st_completed": {"en": "completed", "ta": "முடிந்தது", "hi": "पूरा"},
    "st_in_progress": {"en": "in progress", "ta": "நடைபெறுகிறது", "hi": "चालू"},
    "st_not_started": {"en": "not started", "ta": "தொடங்கவில்லை", "hi": "शुरू नहीं"},
    "cat_material": {"en": "material", "ta": "பொருள்", "hi": "सामग्री"},
    "cat_manpower": {"en": "manpower", "ta": "பணியாளர்", "hi": "मानवशक्ति"},
    "cat_weather": {"en": "weather", "ta": "வானிலை", "hi": "मौसम"},
    "cat_permit": {"en": "permit", "ta": "அனுமதி", "hi": "परमिट"},
    "cat_design": {"en": "design", "ta": "வடிவமைப்பு", "hi": "डिज़ाइन"},
    "cat_equipment": {"en": "equipment", "ta": "உபகரணம்", "hi": "उपकरण"},
}


def lang_of(lang: str | None) -> str:
    return lang if lang in LANGS else "en"


def tr(lang: str | None, key: str, **params) -> str:
    return MESSAGES[key][lang_of(lang)].format(**params)


def word(lang: str | None, prefix: str, value: str) -> str:
    """Translate a code value (status / delay category) when the catalog has it, else keep it."""
    entry = MESSAGES.get(f"{prefix}_{value}")
    return entry[lang_of(lang)] if entry else value


def detect(text: str) -> str | None:
    """Script-based language guess: Tamil or Devanagari letters decide; Latin text gives None (caller's choice wins)."""
    if re.search(r"[஀-௿]", text):
        return "ta"
    if re.search(r"[ऀ-ॿ]", text):
        return "hi"
    return None
