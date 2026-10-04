# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users
- **Primary audience of the public pages (landing, sign-in, sign-up):** Smart India Hackathon SIH26122 judges and Oil India Limited decision makers evaluating whether to adopt and invest. They need to grasp the problem, the mechanism, the proof and the return on investment in minutes, then try the live app.
- **Users of the application:** site supervisors (report progress from the field, often on a phone, in English, Tamil, Hindi or Hinglish), planners / schedulers (validate links, resolve conflicts, keep the schedule of record correct), project managers (progress, delays, reports, ROI).

## Product Purpose
P2E Bridge turns messy daily field reports (DPRs, discipline sheets, supervisor messages) into verified, audited actual start / finish dates on the L5/L6 project schedule (Primavera P6 / MS Project), and turns the clean history into analytics and cited project memory. Success: schedules reflect site reality within minutes instead of days, with zero wrong automatic updates and a planner in the loop for anything uncertain.

## Positioning
Deterministic, on-premise linking with a human in the loop: routine decisions cost zero AI tokens, every automatic change has evidence, a confidence score, an audit entry and an undo; unmatched work is surfaced as a signal, not hidden. No project data leaves the company's servers.

## Operating Context
- Problem statement SIH26122 (Oil India Limited): actuals arrive through DPRs, spreadsheets and verbal updates, disconnected from L5/L6 activity IDs; reconciliation lags days or weeks.
- Synthetic demo project `CGS-EXP-01` (Crude Oil Gathering Station Expansion), as of 2026-09-16.
- Access: role keys issued by an administrator (supervisor / planner / admin). Sign-up is a **request-access** form; an admin reviews requests and issues a key. The sign-in page offers an evaluator **demo account** (username + password) with a one-click "fill demo credentials" button, enabled only for demo deployments.
- Interface languages: English, Tamil, Hindi.

## Capabilities and Constraints
Field report upload (.txt / .docx / .xlsx / .csv), extraction with line/cell evidence, schedule linking (tags, aliases, attributes) with confidence gates and a date-conflict layer, planner review queue, audited apply / override / undo, Primavera P6 XER and MS Project import, CSV / MSPDI export, Time Agent (one-tap menu, chat, voice; en/ta/hi), scoped multilingual assistant (app / project / Oil India with sources), analytics, daily / weekly PM reports, ROI and token efficiency, shadow-mode pilot, silent-activity alerts, project memory Q&A.
Constraints: on-premise; no external AI calls; FastAPI backend serving a React + Vite + TypeScript frontend.

## Brand Commitments
Name: **P2E Bridge** (keep). No logo, colours or fonts are committed yet; a logo will be generated later.

## Evidence on Hand
Measured on the synthetic project: 433 reported items, 261 linked automatically (60.3%) with 0 wrong automatic links; every applied date matches ground truth (48/48 starts, 31/31 finishes); 0 AI tokens; median 5.3 s from upload to schedule update; Q&A 10/10 with citations; P6 XER round trip of 317 activities exact. All figures are synthetic, not real-world accuracy. Oil India facts with sources: `data/company/oil_india.json`. No customer testimonials, logos of clients, or deployment claims exist; do not fabricate them.

## Product Principles
1. AI suggests, humans decide, everything is audited.
2. Zero tokens for routine work; spend intelligence only where it changes the outcome.
3. Evidence over assertion: every number links to its source.
4. Meet field staff where they are: one tap, their language, their phone.
5. Never let the schedule of record drift without a trace.

## Accessibility & Inclusion
Tamil, Hindi and English interface; usable on phones at the site; keyboard and screen-reader basics; respect reduced motion.
