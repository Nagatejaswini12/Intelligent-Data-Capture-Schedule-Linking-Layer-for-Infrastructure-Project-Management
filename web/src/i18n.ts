import { createContext, useContext } from "react";

// Interface language: English, Tamil, Hindi. Tamil and Hindi are translations to be reviewed by native speakers.
// Data (activity names, codes, report text) is never translated; only the interface around it.
export type Lang = "en" | "ta" | "hi";
export const LANGS: { code: Lang; label: string; speech: string }[] = [
  { code: "en", label: "English", speech: "en-IN" },
  { code: "ta", label: "தமிழ்", speech: "ta-IN" },
  { code: "hi", label: "हिन्दी", speech: "hi-IN" },
];

type Entry = [en: string, ta: string, hi: string];
const D: Record<string, Entry> = {
  // shell
  "nav.operate": ["Operate", "செயல்பாடு", "संचालन"],
  "nav.plan": ["Plan", "திட்டம்", "योजना"],
  "nav.intelligence": ["Intelligence", "நுண்ணறிவு", "विश्लेषण"],
  "nav.present": ["Present", "விளக்கம்", "प्रस्तुति"],
  "nav.help": ["Help", "உதவி", "सहायता"],
  "nav.overview": ["Overview", "கண்ணோட்டம்", "अवलोकन"],
  "nav.reports": ["Field Reports", "களஅறிக்கைகள்", "फ़ील्ड रिपोर्ट"],
  "nav.linking": ["Activity Linking", "வேலை இணைப்பு", "कार्य लिंकिंग"],
  "nav.agent": ["Time Agent", "நேர முகவர்", "टाइम एजेंट"],
  "nav.schedule": ["Schedule", "அட்டவணை", "शेड्यूल"],
  "nav.watch": ["Silent Activity Watch", "அமைதியான வேலைகள்", "मौन कार्य निगरानी"],
  "nav.audit": ["Audit Trail", "தணிக்கைப் பதிவு", "ऑडिट ट्रेल"],
  "nav.analytics": ["Analytics", "பகுப்பாய்வு", "विश्लेषण"],
  "nav.roi": ["ROI & Efficiency", "ROI & திறன்", "ROI और दक्षता"],
  "nav.memory": ["Project Memory", "திட்ட நினைவகம்", "प्रोजेक्ट स्मृति"],
  "nav.demo": ["Demo Flow", "டெமோ ஓட்டம்", "डेमो फ़्लो"],
  "nav.guide": ["User Guide", "பயனர் வழிகாட்டி", "उपयोगकर्ता गाइड"],
  "nav.terms": ["Terms of Use", "பயன்பாட்டு விதிமுறைகள்", "उपयोग की शर्तें"],
  "nav.video": ["Video Guide", "வீடியோ வழிகாட்டி", "वीडियो गाइड"],
  "shell.tagline": ["Project control · SIH26122", "திட்டக் கட்டுப்பாடு · SIH26122", "प्रोजेक्ट नियंत्रण · SIH26122"],
  "shell.foot": ["Field execution → AI understanding → schedule linking → human validation → verified progress → project intelligence",
    "களப்பணி → AI புரிதல் → அட்டவணை இணைப்பு → மனிதச் சரிபார்ப்பு → உறுதிசெய்த முன்னேற்றம் → திட்ட நுண்ணறிவு",
    "फ़ील्ड कार्य → AI समझ → शेड्यूल लिंकिंग → मानवीय सत्यापन → सत्यापित प्रगति → प्रोजेक्ट विश्लेषण"],
  "shell.asof": ["As of", "தேதி நிலவரம்", "तारीख़ तक"],
  "shell.live": ["● live", "● நேரலை", "● लाइव"],
  "shell.offline": ["○ offline", "○ இணைப்பில்லை", "○ ऑफ़लाइन"],
  "shell.signout": ["Sign out", "வெளியேறு", "साइन आउट"],
  "shell.language": ["Language", "மொழி", "भाषा"],
  "signin.intro": ["Sign in with your role API key (supervisor, planner or admin). It is kept only in this browser tab.",
    "உங்கள் பங்குச் சாவியுடன் (supervisor, planner அல்லது admin) உள்நுழையவும். அது இந்த உலாவித் தாவலில் மட்டுமே வைக்கப்படும்.",
    "अपनी भूमिका कुंजी (supervisor, planner या admin) से साइन इन करें। यह केवल इसी ब्राउज़र टैब में रहती है।"],
  "signin.key": ["API key", "அணுகல் சாவி", "एक्सेस कुंजी"],
  "signin.go": ["Sign in", "உள்நுழை", "साइन इन"],
  "signin.checking": ["Checking…", "சரிபார்க்கிறது…", "जाँच हो रही है…"],
  "signin.terms": ["By signing in you accept the Terms of Use.", "உள்நுழைவதன் மூலம் பயன்பாட்டு விதிமுறைகளை ஏற்கிறீர்கள்.", "साइन इन करके आप उपयोग की शर्तें स्वीकार करते हैं।"],
  // page titles
  "overview.title": ["Project control overview", "திட்டக் கட்டுப்பாட்டுக் கண்ணோட்டம்", "प्रोजेक्ट नियंत्रण अवलोकन"],
  "overview.sub": ["Recorded history as of {asOf}. Every figure comes from the backend.", "{asOf} வரையிலான பதிவுகள். ஒவ்வொரு எண்ணும் சர்வரிலிருந்து வருகிறது.", "{asOf} तक का रिकॉर्ड। हर आँकड़ा सर्वर से आता है।"],
  "reports.title": ["Field reports", "களஅறிக்கைகள்", "फ़ील्ड रिपोर्ट"],
  "reports.sub": ["Daily progress reports, discipline trackers and Time Agent messages, with what was extracted from each.", "தினசரி அறிக்கைகள், துறைத் தாள்கள், நேர முகவர் செய்திகள் மற்றும் அவற்றிலிருந்து எடுக்கப்பட்டவை.", "दैनिक रिपोर्टें, विभाग ट्रैकर और टाइम एजेंट संदेश, और हर एक से निकाली गई जानकारी।"],
  "linking.title": ["Activity linking & planner review", "வேலை இணைப்பு & திட்டமிடுபவர் சரிபார்ப்பு", "कार्य लिंकिंग और प्लानर समीक्षा"],
  "linking.sub": ["Field report → AI extraction → candidate L5/L6 activity → confidence → planner decision. The linker decides; planners validate.", "களஅறிக்கை → AI பிரித்தெடுப்பு → L5/L6 வேலை → நம்பகத்தன்மை → திட்டமிடுபவர் முடிவு.", "फ़ील्ड रिपोर्ट → AI निष्कर्षण → L5/L6 कार्य → विश्वास स्तर → प्लानर निर्णय।"],
  "agent.title": ["Time Agent", "நேர முகவர்", "टाइम एजेंट"],
  "agent.sub": ["Supervisors report progress in plain words; the agent structures it and hands it to the schedule linker. It never picks an activity itself and never invents a value.",
    "மேற்பார்வையாளர்கள் எளிய சொற்களில் முன்னேற்றத்தைத் தெரிவிக்கிறார்கள்; முகவர் அதை ஒழுங்குபடுத்தி இணைப்பாளருக்கு அனுப்புகிறது. அது தானாக வேலையைத் தேர்வு செய்யாது, மதிப்பை உருவாக்காது.",
    "सुपरवाइज़र सरल शब्दों में प्रगति बताते हैं; एजेंट उसे व्यवस्थित कर लिंकर को देता है। यह ख़ुद कोई काम नहीं चुनता और कोई मान नहीं गढ़ता।"],
  "schedule.title": ["Schedule & verified progress", "அட்டவணை & உறுதிசெய்த முன்னேற்றம்", "शेड्यूल और सत्यापित प्रगति"],
  "schedule.sub": ["L5/L6 activities with planned vs actual dates as of {asOf}. Actuals change only through audited apply / override / undo.", "{asOf} நிலவரப்படி L5/L6 வேலைகளின் திட்டமிட்ட மற்றும் உண்மைத் தேதிகள். தணிக்கை செய்யப்பட்ட மாற்றங்கள் மட்டுமே.", "{asOf} तक L5/L6 कार्यों की नियोजित और वास्तविक तारीख़ें। बदलाव केवल ऑडिट के साथ।"],
  "watch.title": ["Silent activity watch", "அமைதியான வேலைகள்", "मौन कार्य निगरानी"],
  "watch.sub": ["These activities may need a field update: the plan expects them to be active, but no linked report mentions them recently.", "இந்த வேலைகள் நடைபெற வேண்டும், ஆனால் சமீபத்திய அறிக்கைகளில் இல்லை; களப் புதுப்பிப்பு தேவைப்படலாம்.", "योजना के अनुसार ये काम चालू होने चाहिए, पर हाल की किसी रिपोर्ट में नहीं हैं।"],
  "watch.ask": ["Ask the Time Agent for a checklist →", "நேர முகவரிடம் பட்டியல் கேளுங்கள் →", "टाइम एजेंट से चेकलिस्ट माँगें →"],
  "audit.title": ["Audit trail", "தணிக்கைப் பதிவு", "ऑडिट ट्रेल"],
  "audit.sub": ["Append-only record of every schedule change: before → after, who, which rule, which field reports. Undo writes a compensating entry; nothing is erased.", "ஒவ்வொரு அட்டவணை மாற்றத்தின் நிரந்தரப் பதிவு: முன் → பின், யார், எந்த விதி, எந்த அறிக்கைகள். எதுவும் அழிக்கப்படாது.", "हर शेड्यूल बदलाव का स्थायी रिकॉर्ड: पहले → बाद, किसने, कौन-सा नियम, कौन-सी रिपोर्टें। कुछ भी मिटाया नहीं जाता।"],
  "analytics.title": ["Project analytics", "திட்டப் பகுப்பாய்வு", "प्रोजेक्ट विश्लेषण"],
  "analytics.sub": ["Computed by the backend from the recorded history as of {asOf}.", "{asOf} வரையிலான பதிவுகளிலிருந்து கணக்கிடப்பட்டது.", "{asOf} तक के रिकॉर्ड से गणना।"],
  "analytics.daily": ["Daily PM report", "தினசரி PM அறிக்கை", "दैनिक PM रिपोर्ट"],
  "analytics.weekly": ["Weekly PM report", "வாராந்திர PM அறிக்கை", "साप्ताहिक PM रिपोर्ट"],
  "analytics.dataset": ["Download actual-progress dataset (CSV)", "உண்மை முன்னேற்றத் தரவு (CSV) பதிவிறக்கு", "वास्तविक प्रगति डेटा (CSV) डाउनलोड करें"],
  "memory.title": ["Project memory", "திட்ட நினைவகம்", "प्रोजेक्ट स्मृति"],
  "memory.sub": ["Ask the recorded project history. Answers come from fixed query templates or cited retrieval; every number cites its records.", "பதிவான திட்ட வரலாற்றைக் கேளுங்கள். ஒவ்வொரு பதிலும் அதன் பதிவுகளைக் குறிப்பிடும்.", "रिकॉर्ड किए गए प्रोजेक्ट इतिहास से पूछें। हर जवाब अपने रिकॉर्ड बताता है।"],
  "memory.tokens": ["fixed query · 0 AI tokens", "நிலையான வினவல் · 0 AI டோக்கன்", "तय क्वेरी · 0 AI टोकन"],
  "demo.title": ["Demo flow", "டெமோ ஓட்டம்", "डेमो फ़्लो"],
  "demo.sub": ["A few-minute walk through the real system (as of {asOf}). Each step calls the live API.", "உண்மையான அமைப்பின் சில நிமிட விளக்கம் ({asOf}). ஒவ்வொரு படியும் நேரடி API-ஐ அழைக்கிறது.", "असली सिस्टम की कुछ मिनट की झलक ({asOf})। हर चरण लाइव API को बुलाता है।"],
  "roi.title": ["ROI & efficiency", "ROI & திறன்", "ROI और दक्षता"],
  "roi.sub": ["What the system saved as of {asOf}, from the recorded decisions. Rupee and token figures are estimates from the assumptions below.", "{asOf} வரை பதிவான முடிவுகளின்படி அமைப்பு சேமித்தவை. ரூபாய், டோக்கன் எண்கள் கீழே உள்ள அனுமானங்களின் மதிப்பீடுகள்.", "{asOf} तक दर्ज निर्णयों के आधार पर सिस्टम ने क्या बचाया। रुपये और टोकन आँकड़े नीचे की मान्यताओं पर आधारित अनुमान हैं।"],
  // overview KPIs / cards
  "kpi.complete": ["Actually complete", "உண்மையில் முடிந்தவை", "वास्तव में पूरे"],
  "kpi.plannedComplete": ["Planned complete by as-of", "திட்டப்படி முடிந்திருக்க வேண்டியவை", "योजना अनुसार पूरे होने थे"],
  "kpi.inProgress": ["In progress", "நடைபெறுகிறது", "चालू"],
  "kpi.review": ["Needs planner review", "திட்டமிடுபவர் சரிபார்ப்பு தேவை", "प्लानर समीक्षा ज़रूरी"],
  "kpi.conflicts": ["Cross-source conflicts", "முரண்பட்ட அறிக்கைகள்", "विरोधाभासी रिपोर्टें"],
  "kpi.unmatched": ["Unmatched reports", "பொருந்தாத அறிக்கைகள்", "बेमेल रिपोर्टें"],
  "kpi.silent": ["Silent activities", "அமைதியான வேலைகள்", "मौन कार्य"],
  "kpi.startedLate": ["Started late", "தாமதமாகத் தொடங்கியவை", "देर से शुरू"],
  "kpi.finishedLate": ["Finished late", "தாமதமாக முடிந்தவை", "देर से पूरे"],
  "kpi.overdue": ["Overdue, not started", "காலம் கடந்தும் தொடங்காதவை", "समय बीता, शुरू नहीं"],
  "card.plannedVsActual": ["Planned vs actual completion by discipline", "துறைவாரியாகத் திட்டமிட்ட / உண்மை முடிவு", "विभाग अनुसार नियोजित बनाम वास्तविक"],
  "card.statusByDiscipline": ["Status by discipline", "துறைவாரியான நிலை", "विभाग अनुसार स्थिति"],
  "card.freshness": ["Reporting freshness (daily progress reports)", "அறிக்கைப் புதுமை (தினசரி அறிக்கைகள்)", "रिपोर्टिंग ताज़गी (दैनिक रिपोर्टें)"],
  "card.delayCauses": ["Reported delay causes", "தெரிவிக்கப்பட்ட தாமதக் காரணங்கள்", "बताए गए देरी के कारण"],
  // agent page
  "agent.discipline": ["Supervisor discipline", "மேற்பார்வையாளர் துறை", "सुपरवाइज़र विभाग"],
  "agent.stateIt": ["— state it in the message —", "— செய்தியில் குறிப்பிடவும் —", "— संदेश में बताएँ —"],
  "agent.time": ["Reporting time", "அறிக்கை நேரம்", "रिपोर्ट का समय"],
  "agent.speak": ["Speak replies", "பதில்களைப் பேசு", "जवाब बोलें"],
  "agent.menu": ["My activities today", "இன்றைய என் வேலைகள்", "आज के मेरे काम"],
  "agent.pick": ["Pick your discipline to get a one-tap list (no typing, no AI tokens).", "ஒரே தொடுதல் பட்டியலுக்கு உங்கள் துறையைத் தேர்ந்தெடுக்கவும் (தட்டச்சு இல்லை, AI டோக்கன் இல்லை).", "एक-टैप सूची के लिए अपना विभाग चुनें (कोई टाइपिंग नहीं, कोई AI टोकन नहीं)।"],
  "agent.nothing": ["Nothing expected today.", "இன்று எதிர்பார்க்கப்படுவது எதுவும் இல்லை.", "आज कुछ अपेक्षित नहीं।"],
  "agent.reported": ["reported", "பதிவானது", "दर्ज"],
  "agent.start": ["Start", "தொடக்கம்", "शुरू"],
  "agent.finish": ["Finish", "முடிவு", "पूरा"],
  "agent.hold": ["Hold", "நிறுத்தம்", "रोक"],
  "agent.send": ["Send", "அனுப்பு", "भेजें"],
  "agent.placeholder": ["e.g. Line 1203 hydrotest started today at 9 am", "எ.கா. Line 1203 hydrotest இன்று தொடங்கியது", "जैसे: Line 1203 hydrotest आज शुरू हुआ"],
  "agent.empty": ["Example: “LT-4011 loop check finished yesterday at 4 pm”, or ask “What should I report today?”.", "உதாரணம்: “LT-4011 loop check நேற்று முடிந்தது”, அல்லது “What should I report today?” என்று கேளுங்கள்.", "उदाहरण: “LT-4011 loop check कल पूरा हो गया”, या पूछें “What should I report today?”।"],
  "agent.undo": ["Undo", "திரும்பப் பெறு", "पूर्ववत"],
  "agent.retracted": ["retracted: in planner review", "திரும்பப் பெறப்பட்டது: சரிபார்ப்பில்", "वापस लिया: प्लानर समीक्षा में"],
  "agent.undone": ["Sent back to planner review. Nothing will be applied from that report.", "திட்டமிடுபவர் சரிபார்ப்புக்குத் திருப்பப்பட்டது. அந்த அறிக்கையிலிருந்து எதுவும் பயன்படுத்தப்படாது.", "प्लानर समीक्षा को वापस भेजा गया। उस रिपोर्ट से कुछ लागू नहीं होगा।"],
  "agent.nothingUndo": ["Nothing to undo in this session.", "இந்த அமர்வில் திரும்பப் பெற எதுவும் இல்லை.", "इस सत्र में पूर्ववत करने को कुछ नहीं।"],
  "agent.listening": ["Listening…", "கேட்கிறது…", "सुन रहा है…"],
  "tap.start": ["started today", "இன்று தொடங்கியது", "आज शुरू हुआ"],
  "tap.finish": ["completed today", "இன்று முடிந்தது", "आज पूरा हो गया"],
  "tap.hold": ["on hold today", "இன்று நிறுத்தப்பட்டது", "आज रुक गया"],
  // ROI
  "roi.auto": ["Linked automatically", "தானாக இணைக்கப்பட்டவை", "अपने-आप जुड़े"],
  "roi.autoHint": ["{a} of {n} reported items", "{n} பதிவுகளில் {a}", "{n} में से {a} आइटम"],
  "roi.tokens": ["AI tokens per 1,000 reports", "1,000 அறிக்கைக்கு AI டோக்கன்", "प्रति 1,000 रिपोर्ट AI टोकन"],
  "roi.tokensHint": ["vs {n} if an LLM read everything", "எல்லாவற்றையும் LLM படித்தால் {n}", "अगर LLM सब पढ़े तो {n}"],
  "roi.cost": ["₹ per 1,000 reports (AI)", "1,000 அறிக்கைக்கு ₹ (AI)", "प्रति 1,000 रिपोर्ट ₹ (AI)"],
  "roi.costHint": ["vs {n} LLM-for-everything", "LLM எல்லாவற்றுக்கும் என்றால் {n}", "सब कुछ LLM से: {n}"],
  "roi.saved": ["Planner time saved", "சேமித்த திட்டமிடுபவர் நேரம்", "बचा प्लानर समय"],
  "roi.savedHint": ["{n} at the assumed rate", "அனுமான விகிதத்தில் {n}", "मानी गई दर पर {n}"],
  "roi.speed": ["Report → schedule", "அறிக்கை → அட்டவணை", "रिपोर्ट → शेड्यूल"],
  "roi.speedHint": ["median system time vs ~{n} days manually", "அமைப்பின் நடுநிலை நேரம்; கையால் ~{n} நாட்கள்", "सिस्टम का औसत समय; हाथ से ~{n} दिन"],
  "roi.alerts": ["Should have started / finished", "தொடங்கியிருக்க / முடிந்திருக்க வேண்டியவை", "शुरू / पूरे हो जाने चाहिए थे"],
  "roi.alertsHint": ["expected work, no report in 3 days", "எதிர்பார்த்த வேலை, 3 நாளாக அறிக்கை இல்லை", "अपेक्षित काम, 3 दिन से रिपोर्ट नहीं"],
  "roi.who": ["Who decided each reported item", "ஒவ்வொரு பதிவையும் யார் முடிவு செய்தது", "हर आइटम का निर्णय किसने लिया"],
  "roi.whoNote": ["Automatic = deterministic linker, 0 tokens. Planner = a human confirmed, rejected or held it.", "தானியங்கி = நிர்ணய இணைப்பாளர், 0 டோக்கன். திட்டமிடுபவர் = மனிதர் உறுதிசெய்தார், நிராகரித்தார் அல்லது நிறுத்தினார்.", "स्वचालित = नियम-आधारित लिंकर, 0 टोकन। प्लानर = किसी व्यक्ति ने पुष्टि, अस्वीकार या रोका।"],
  "roi.byEvidence": ["Automatic matches by evidence", "ஆதார வகைப்படி தானியங்கிப் பொருத்தங்கள்", "सबूत अनुसार स्वचालित मिलान"],
  "roi.assumptions": ["Assumptions (replace with OIL figures)", "அனுமானங்கள் (OIL எண்களால் மாற்றவும்)", "मान्यताएँ (OIL के आँकड़ों से बदलें)"],
  "roi.recalc": ["Recalculate", "மீண்டும் கணக்கிடு", "फिर से गणना करें"],
  "roi.shadow": ["Pilot: shadow mode", "முன்னோட்டம்: shadow mode", "पायलट: shadow mode"],
  "roi.shadowText": ["In shadow mode the system links and proposes everything but writes no actual dates automatically. It would update {n} activities; {b} wait for planner review. Switching needs a planner key.",
    "shadow mode-இல் அமைப்பு எல்லாவற்றையும் இணைத்துப் பரிந்துரைக்கும், ஆனால் தானாகத் தேதிகளை எழுதாது. {n} வேலைகளைப் புதுப்பிக்கும்; {b} சரிபார்ப்புக்குக் காத்திருக்கின்றன. மாற்ற planner சாவி தேவை.",
    "shadow mode में सिस्टम सब कुछ जोड़कर सुझाता है पर अपने-आप तारीख़ें नहीं लिखता। यह {n} कामों को अपडेट करेगा; {b} प्लानर समीक्षा में हैं। बदलने के लिए planner कुंजी चाहिए।"],
  "roi.on": ["Turn on", "இயக்கு", "चालू करें"],
  "roi.off": ["Turn off (apply for real)", "நிறுத்து (உண்மையாகப் பயன்படுத்து)", "बंद करें (असल में लागू करें)"],
  "roi.alertTable": ["Alerts: expected work with no report ({n})", "எச்சரிக்கைகள்: அறிக்கை இல்லாத எதிர்பார்த்த வேலைகள் ({n})", "अलर्ट: बिना रिपोर्ट वाला अपेक्षित काम ({n})"],
  "roi.allGood": ["Every expected activity has a recent report.", "எதிர்பார்த்த அனைத்து வேலைகளுக்கும் சமீபத்திய அறிக்கை உள்ளது.", "हर अपेक्षित काम की हाल की रिपोर्ट है।"],
  "roi.a.minutes": ["Planner minutes per item (manual)", "ஒரு பதிவுக்கு திட்டமிடுபவர் நிமிடங்கள் (கையால்)", "प्रति आइटम प्लानर मिनट (हाथ से)"],
  "roi.a.rate": ["Planner cost ₹/hour", "திட்டமிடுபவர் செலவு ₹/மணி", "प्लानर लागत ₹/घंटा"],
  "roi.a.lag": ["Report → schedule today (days)", "இன்று அறிக்கை → அட்டவணை (நாட்கள்)", "आज रिपोर्ट → शेड्यूल (दिन)"],
  "roi.a.tokens": ["Tokens per item if an LLM read it", "LLM படித்தால் ஒரு பதிவுக்கு டோக்கன்", "LLM पढ़े तो प्रति आइटम टोकन"],
  "roi.a.price": ["Cloud LLM ₹ per 1,000 tokens", "கிளவுட் LLM ₹ / 1,000 டோக்கன்", "क्लाउड LLM ₹ / 1,000 टोकन"],
  // assistant
  "as.open": ["Ask P2E", "P2E-இடம் கேள்", "P2E से पूछें"],
  "as.title": ["P2E assistant", "P2E உதவியாளர்", "P2E सहायक"],
  "as.scope": ["Answers only about this app, this project and Oil India Limited, with sources.", "இந்தச் செயலி, இந்தத் திட்டம், ஆயில் இந்தியா பற்றி மட்டும், ஆதாரங்களுடன் பதிலளிக்கும்.", "केवल इस ऐप, इस प्रोजेक्ट और ऑयल इंडिया के बारे में, स्रोत सहित जवाब देता है।"],
  "as.placeholder": ["Ask a question…", "கேள்வி கேளுங்கள்…", "सवाल पूछें…"],
  "as.ask": ["Ask", "கேள்", "पूछें"],
  "as.sources": ["Sources", "ஆதாரங்கள்", "स्रोत"],
  "as.close": ["Close", "மூடு", "बंद करें"],
  "as.ex1": ["What delayed piping work?", "குழாய் வேலை ஏன் தாமதம்?", "पाइपिंग काम में देरी क्यों हुई?"],
  "as.ex2": ["What is Oil India's net zero target?", "ஆயில் இந்தியாவின் நிகர பூஜ்ஜிய இலக்கு என்ன?", "ऑयल इंडिया का नेट ज़ीरो लक्ष्य क्या है?"],
  "as.ex3": ["How do I upload a report?", "அறிக்கையை எப்படிப் பதிவேற்றுவது?", "रिपोर्ट कैसे अपलोड करें?"],
  // guide / terms / video
  "guide.title": ["User guide", "பயனர் வழிகாட்டி", "उपयोगकर्ता गाइड"],
  "guide.sub": ["How to use P2E Bridge, step by step, for supervisors, planners and managers.", "மேற்பார்வையாளர்கள், திட்டமிடுபவர்கள், மேலாளர்களுக்கான P2E Bridge படிப்படியான வழிகாட்டி.", "सुपरवाइज़र, प्लानर और प्रबंधकों के लिए P2E Bridge की चरण-दर-चरण गाइड।"],
  "terms.draft": ["Draft for review by the operator's legal team; not legal advice.", "இயக்குநரின் சட்டக் குழுவின் சரிபார்ப்புக்கான வரைவு; சட்ட ஆலோசனை அல்ல.", "संचालक की कानूनी टीम की समीक्षा हेतु मसौदा; कानूनी सलाह नहीं।"],
  "video.title": ["Video guide", "வீடியோ வழிகாட்டி", "वीडियो गाइड"],
  "video.sub": ["A short video explanation of P2E Bridge.", "P2E Bridge பற்றிய சிறிய வீடியோ விளக்கம்.", "P2E Bridge की छोटी वीडियो व्याख्या।"],
  "video.missing": ["The video has not been added yet. Place it at web/public/guide-video.mp4 and rebuild.", "வீடியோ இன்னும் சேர்க்கப்படவில்லை. web/public/guide-video.mp4 இல் வைத்து மீண்டும் build செய்யவும்.", "वीडियो अभी नहीं जोड़ा गया। इसे web/public/guide-video.mp4 पर रखें और फिर से build करें।"],
};

export function translate(lang: Lang, key: string, params?: Record<string, string | number>): string {
  const e = D[key];
  let s = e ? e[{ en: 0, ta: 1, hi: 2 }[lang]] || e[0] : key;
  for (const [k, v] of Object.entries(params ?? {})) s = s.replaceAll(`{${k}}`, String(v));
  return s;
}

/** Keys missing a translation (the test suite keeps this empty). */
export function missingTranslations(): string[] {
  return Object.entries(D).filter(([, e]) => e.length !== 3 || e.some((s) => !s)).map(([k]) => k);
}

export function loadLang(): Lang {
  try {
    const v = localStorage.getItem("p2e.lang");
    return v === "ta" || v === "hi" ? v : "en";
  } catch {
    return "en";
  }
}

export function saveLang(lang: Lang) {
  try { localStorage.setItem("p2e.lang", lang); } catch { /* ignore */ }
  if (typeof document !== "undefined") document.documentElement.lang = lang;
}

export const LangContext = createContext<{ lang: Lang; setLang: (l: Lang) => void }>({ lang: "en", setLang: () => {} });

export function useT() {
  const { lang, setLang } = useContext(LangContext);
  return { lang, setLang, t: (key: string, params?: Record<string, string | number>) => translate(lang, key, params),
    speech: LANGS.find((l) => l.code === lang)!.speech };
}
