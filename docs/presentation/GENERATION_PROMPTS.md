# P2E Bridge: video and image generation prompts

Copy each block as-is into your generator. Every video prompt is **one 8-second clip**.

| Use in the app | Clips (8 s each) | Total | Save as (for me to wire in) |
|---|---|---|---|
| Landing page hero background | 3 | 24 s | `web/public/media/landing-1.mp4`, `landing-2.mp4`, `landing-3.mp4` |
| Sign-in page background | 2 | 16 s | `web/public/media/signin-1.mp4`, `signin-2.mp4` |
| Sign-up (request access) background | 2 | 16 s | `web/public/media/signup-1.mp4`, `signup-2.mp4` |
| **Videos total** | **7 prompts** | **56 s** | |
| App logo | 1 image (+ 1 mark-only variant) | | `web/public/brand/logo.png`, `logo-mark.png` |
| Agent icons | 4 images | | `web/public/brand/agent-time.png`, `agent-linker.png`, `agent-watch.png`, `agent-memory.png` |
| Chatbot (Ask P2E) avatar | 1 image | | `web/public/brand/chatbot.png` |
| Voice assistant icon | 1 image | | `web/public/brand/voice.png` |
| **Images total** | **8 prompts** | | |

**Shared look for everything** (already inside each prompt): bright premium light theme, cool white and pale silver-blue ground, deep navy (#14213D) as the strong colour, one violet accent (#5B3FD1) for "verified / linked", soft daylight, crisp and minimal, no clutter. **No text, letters, numbers or logos inside any video**, because the app overlays its own text and translations (English, Tamil, Hindi).

**Generator settings for every video:** 16:9, 1920×1080 (or the highest your tool allows), 24 or 30 fps, 8 seconds, no audio, slow steady camera, **seamless loop where it says so** (the first and last frame should match).

---

## Landing page hero (3 clips, played one after another as the page scrolls)

Together they tell the product story: scattered field reports → linked by P2E Bridge → a verified schedule.

### Landing clip 1 of 3: "Field reality" (8 s)
```
Cinematic 8-second shot, 16:9, photorealistic with a clean premium look. Early-morning soft daylight over a modern oil and gas construction site in India: a crude oil gathering station under construction with steel pipe racks, insulated pipelines, a storage tank shell, a pump skid and cable trays, all spotless and orderly. Slow, smooth aerial dolly moving forward and slightly down across the pipe racks. Thin translucent white paper sheets (daily progress reports) drift gently upward from different work areas into the air like light flakes, catching the sun, each sheet faint and blank with no readable text. Colour grade: bright, airy, cool whites and pale silver-blue sky, deep navy steel shadows, a few subtle violet light glints. Shallow atmospheric haze, high dynamic range, ultra sharp, premium architectural film look. No people's faces, no text, no logos, no watermark, no lens flare overload. Calm, confident, expensive.
```

### Landing clip 2 of 3: "The bridge links everything" (8 s)
```
Cinematic 8-second shot, 16:9, abstract 3D on a bright white studio background. The floating white paper sheets from a construction site arrive from the left and each one turns into a thin glowing line of light. The lines travel across the frame and snap precisely into a clean three-dimensional timeline of rounded horizontal bars (a schedule / Gantt structure) floating in space on the right. At the moment each line connects, a soft violet circular pulse appears like a rubber-stamp impression of light, then fades. Slow orbiting camera, 15 degrees around the structure. Materials: frosted glass bars, satin white surfaces, deep navy edges, violet (#5B3FD1) connection glow, soft global illumination, gentle reflections on a glossy white floor. Precise, engineered, calm motion with smooth easing. No text, no numbers, no logos, no UI chrome, no watermark. Premium product-launch film quality.
```

### Landing clip 3 of 3: "Verified schedule of record" (8 s, seamless loop)
```
Cinematic 8-second seamless loop, 16:9, abstract 3D, bright and premium. A wide, elegant three-dimensional project timeline of frosted glass bars floats above a glossy white floor, arranged in neat rows like an engineering schedule. A thin vertical line of soft violet light (marking "today") sweeps slowly from left to right across the bars; bars it passes glow briefly from pale silver to solid deep navy, as if confirmed. Tiny particles of light drift upward like dust in sunlight. Very slow camera push-in with a slight parallax. Palette: cool white, pale silver-blue, deep navy (#14213D), single violet accent (#5B3FD1). Soft daylight from the top left, gentle shadows, high-end product render, ultra clean. The first and last frames match exactly for a seamless loop. No text, no numbers, no logos, no people, no watermark.
```

---

## Sign-in page background (2 clips)

Calm and premium so the sign-in card stays readable on top of it. Keep the centre of the frame quieter.

### Sign-in clip 1 of 2 (8 s, seamless loop)
```
Cinematic 8-second seamless loop, 16:9, very calm and minimal. Close-up abstract macro of brushed steel industrial pipework and flanges, painted in soft satin white and pale silver-blue, lit by gentle morning daylight. The camera glides extremely slowly sideways along the pipes. Thin lines of soft violet light flow slowly inside the transparent sections of the pipes like data moving through a pipeline. Very shallow depth of field with creamy bokeh, the centre of the frame softly out of focus and brighter so a login form can sit on top. Palette: cool white, silver-blue, deep navy shadows, subtle violet glow (#5B3FD1). Premium, quiet, trustworthy. First and last frames match. No text, no logos, no people, no watermark, no harsh contrast.
```

### Sign-in clip 2 of 2 (8 s, seamless loop)
```
Cinematic 8-second seamless loop, 16:9, abstract and minimal. A soft white surface covered with faint engineering grid lines and thin ruled lines like a premium printed site register, seen at a low angle. Very slowly, delicate translucent violet ink-like light blooms appear and fade in different spots like gentle stamp impressions, while a slow light sweep passes across the surface. Camera drifts forward almost imperceptibly. Bright, airy daylight, soft shadows, shallow depth of field with the centre softly blurred and bright for overlaid UI. Palette: cool white, pale grey-blue grid, deep navy accents, violet (#5B3FD1). First and last frames match. No readable text, no numbers, no logos, no watermark.
```

---

## Sign-up (request access) background (2 clips)

Feels like "joining the team": welcoming, a little warmer in motion, still light and premium.

### Sign-up clip 1 of 2 (8 s, seamless loop)
```
Cinematic 8-second seamless loop, 16:9, photorealistic but soft and premium. A bright modern project control room with large windows overlooking an oil and gas construction site at golden-white morning light. Clean white desks, large soft-glowing wall screens showing only abstract blurred shapes of timelines and charts (nothing readable). The camera slowly dollies along the room toward the windows. Light, airy, minimal, with deep navy furniture accents and a subtle violet glow on the screens (#5B3FD1). Shallow depth of field, the left half of the frame softly blurred and bright so a form can sit on top. No people's faces, no readable text, no logos, no watermark. First and last frames match for a seamless loop.
```

### Sign-up clip 2 of 2 (8 s, seamless loop)
```
Cinematic 8-second seamless loop, 16:9, abstract 3D. On a bright white background, hundreds of small soft-white spheres (people and teams) drift slowly and gently connect with thin luminous navy lines into an elegant network that slowly rotates, with occasional soft violet pulses travelling along the connections. Soft global illumination, glossy white floor reflections, very shallow depth of field, calm and welcoming motion with smooth easing. Palette: cool white, pale silver-blue, deep navy (#14213D), violet accent (#5B3FD1). The left half stays brighter and less busy for an overlaid form. First and last frames match exactly. No text, no logos, no watermark.
```

---

## App logo (images)

### Logo 1: full logo (icon + wordmark)
```
Premium minimal logo for a software product named "P2E Bridge", used by Oil India Limited project teams to turn daily field reports into a verified project schedule. Symbol: a clean geometric bridge arc that also reads as a connection line linking a small square (a field report) on the left to three short horizontal bars (a schedule) on the right; one small violet dot where the line lands, like a verification stamp. Flat vector style, precise geometry, balanced negative space, works at 16 px and on a billboard. Colours: deep navy #14213D for the symbol, violet #5B3FD1 for the single accent dot, on a pure white background. Wordmark "P2E Bridge" to the right of the symbol in a modern, confident geometric sans-serif, navy, medium weight, generous letter spacing. No gradients, no 3D, no shadows, no oil drops, no flames, no clip-art, no extra text. Centered, high resolution, transparent-ready.
```

### Logo 2: mark only (app icon / favicon)
```
App icon version of the "P2E Bridge" symbol only, no text: a clean geometric bridge arc linking a small square on the left to three short horizontal bars on the right, with one small violet dot where the line lands. Deep navy #14213D symbol, violet #5B3FD1 accent dot, centered on a rounded-square white tile with a very subtle cool-grey border. Flat vector, perfectly balanced, readable at 16x16 and 512x512. No gradients, no shadows, no text.
```

---

## Agent icons (4 images, one consistent set)

Use the same style line for all four so they look like one family.

```
STYLE FOR ALL FOUR: minimal premium line icon set, 2px rounded strokes, deep navy #14213D lines with exactly one violet #5B3FD1 accent element, inside a soft white circle with a very light cool-grey ring, flat vector, no text, no gradients, no shadows, consistent stroke width and corner radius, centered, 1024x1024, transparent background.
```

### Agent 1: Time Agent (supervisors report progress)
```
[STYLE FOR ALL FOUR] Icon of a clipboard with a small clock at its top corner and a check mark; the check mark is violet.
```

### Agent 2: Linker (matches reports to schedule activities)
```
[STYLE FOR ALL FOUR] Icon of a short curved connection line joining a small document on the left to three stacked horizontal bars on the right; the connection node in the middle is a violet dot.
```

### Agent 3: Watch (spots expected work with no report)
```
[STYLE FOR ALL FOUR] Icon of an eye shape whose pupil is a small calendar square; a tiny violet alert dot sits at the top right.
```

### Agent 4: Memory (answers questions with cited sources)
```
[STYLE FOR ALL FOUR] Icon of an open book with a small magnifying glass over the right page; the lens rim is violet.
```

---

## Chatbot avatar: "Ask P2E"
```
Friendly but professional assistant avatar for "Ask P2E", the in-app assistant of P2E Bridge (answers questions about the app, the project and Oil India Limited in English, Tamil and Hindi). A soft rounded speech-bubble shape in deep navy #14213D containing a minimal abstract bridge arc in white, with a small violet #5B3FD1 dot as the "voice" of the assistant. Flat vector, gentle rounded geometry, no face, no robot, no cartoon, no text, centered on a white circle with a light cool-grey ring. Premium, calm, trustworthy, readable at 32 px. 1024x1024, transparent background.
```

## Voice assistant icon
```
Premium minimal icon for the voice assistant of P2E Bridge: a rounded microphone shape in deep navy #14213D with three short concentric sound-wave arcs on its right side; the outermost arc is violet #5B3FD1. Flat vector, 2px rounded strokes matching a line-icon family, no text, no gradients, no shadows, centered in a soft white circle with a light cool-grey ring. Readable at 24 px. 1024x1024, transparent background.
```

---

### Negative prompt (paste into the "avoid" box if your tool has one)
```
text, letters, numbers, captions, logos, watermark, signature, people's faces, cartoon, low resolution, blur artifacts, flicker, jitter, warped geometry, heavy lens flare, oversaturated neon, dark moody night scene, clutter
```

### After generating
Send me the files (or drop them at the paths in the table at the top) and I'll wire them into the landing, sign-in and sign-up pages, with a still-image fallback and reduced-motion support.
