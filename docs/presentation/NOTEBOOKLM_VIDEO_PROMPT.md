# NotebookLM prompt: P2E Bridge user-guide video

**Sources to add to the notebook first:** `README.md`, `docs/presentation/EVALUATOR_QA.md`, `docs/plan/UPGRADE_PLAN.md`, and the user guide text (`data/help/guide.json`, or copy the in-app *User Guide* page into a document).
**Where it goes in the app:** save the exported video as `web/public/guide-video.mp4` (create the `public` folder), then run `cd web; npm run build`. The *Video Guide* page picks it up automatically.
**Other languages:** if NotebookLM offers an output language for Video Overviews, generate Tamil and Hindi versions with the same prompt.

Paste this into **Video Overview → Customize**:

```
Create a friendly, practical user-guide video (about 6–8 minutes) for "P2E Bridge", the field-progress and schedule-linking application built for Oil India Limited (Smart India Hackathon problem SIH26122). Audience: site supervisors, planners and project managers who will use the app. Explain every step on screen in plain language, as a walkthrough, not a pitch. Do not invent features or numbers that are not in the sources.

1. WHAT IT IS (40s)
P2E Bridge turns daily site progress reports into verified, audited actual dates on the project schedule (Primavera P6 / MS Project). It runs on the company's own servers; project data never goes to an external AI service. Routine decisions cost zero AI tokens.

2. SIGNING IN AND SETTING UP (40s)
Sign in with the access key from your administrator (supervisor, planner or admin). Choose the language in the top bar: English, Tamil or Hindi; the screens and the assistant follow it. Set "As of" to the date you are working on. The Terms of Use are linked on the sign-in screen.

3. SUPERVISORS: REPORTING PROGRESS (1.5 min)
Open Time Agent and pick your discipline. Fastest way: under "My activities today", tap Start, Finish or Hold next to the activity: no typing, no AI cost. Or type or speak a message in English, Tamil or Hindi, for example "Line 1203 hydrotest started today", "LT-4011 loop check நேற்று முடிந்தது", "P-101A grouting कल पूरा हो गया". If something is missing, the agent asks one short question. Type "undo" to send your last report back to the planner; say "it" or "that one" for the activity you just reported. Press the microphone to speak (Chrome or Edge), and tick "Speak replies" to hear answers.

4. UPLOADING FIELD REPORTS (40s)
Field Reports: upload a daily progress report (.txt or .docx) or a discipline sheet (.xlsx or .csv), then press Process. Every extracted event links to the exact line or cell it came from (Evidence).

5. PLANNERS: REVIEW AND APPROVE (1 min)
Activity Linking shows each report with its suggested activity, confidence and evidence. Confident matches are applied automatically; uncertain, conflicting or new work waits in the review queue. Approve, choose another activity, mark new work, or override a date. Every change is recorded in the Audit Trail and can be undone; the trail is tamper-evident.

6. SCHEDULE, REPORTS AND ROI (1 min)
Schedule shows planned versus actual dates and exports updated actuals for P6 / MS Project; the plan itself can be imported from Primavera P6 (.xer). Analytics → Daily or Weekly PM report gives a printable report (Save as PDF). ROI & Efficiency shows how many reports were linked automatically, AI tokens and cost per 1,000 reports, planner hours saved, and work that should have started or finished but has no report. Shadow mode lets a live project run the system alongside the current process without writing any dates automatically.

7. THE ASSISTANT (40s)
Press "Ask P2E" (bottom right) on any screen. Type or speak in English, Tamil or Hindi. It answers questions about the app, the project's progress and Oil India Limited (results, production, environment and net zero 2040, CSR, market and employee reviews), always with sources and dates. It politely declines anything else.

8. TIPS AND CLOSING (30s)
Recap: report with one tap or one sentence, planners confirm anything uncertain, everything is audited. Point viewers to the User Guide page and the Terms of Use in the Help menu.

Style: calm narrator, short sentences, on-screen labels for button names (Time Agent, My activities today, Undo, Activity Linking, ROI & Efficiency, Ask P2E). Show the language switch once in each of English, Tamil and Hindi.
```
