# Official resources used by P2E Bridge

P2E Bridge (SIH26122, Oil India Limited) uses **only official Government of India and Oil India resources**. This page says, honestly, which ones the product uses, how, and which ones on the shortlist do not apply to this problem statement.

| Resource | Owner | What it offers | How P2E Bridge uses it | Status |
|---|---|---|---|---|
| **BHASHINI** | MeitY, Government of India | Speech-to-text (ASR), text-to-speech (TTS) and translation (NMT) for Indian languages | Voice for the **Time Agent** and the **Ask P2E** assistant in English, Hindi, Tamil and **Assamese**; Assamese speech is translated to English so the Time Agent can link it, and answers are translated back and read aloud | **Implemented** (`p2e/integrations/bhashini.py`, `/api/v1/speech/*`, `web/src/hooks/useSpeech.ts`); switched on by setting BHASHINI keys; falls back to browser speech |
| **AIKosh** (IndiaAI) | IndiaAI Mission, MeitY | Registry of Indian AI models and datasets, e.g. AI4Bharat **IndicConformer** (multilingual ASR) and **IndicTrans2** (translation for all 22 scheduled languages) | **On-premise mode**: the same BHASHINI client can call a self-hosted inference endpoint running these AIKosh models, so no audio or text leaves Oil India's network (`BHASHINI_INFERENCE_URL`) | **Implemented** (client mode + tests); model hosting is a deployment step |
| **Oil India Limited official sources** | Oil India Limited | Annual Report 2024-25, Financial Results, Net Zero 2040 and CSR pages on oil-india.com | Every company fact the assistant gives (overview, financial results, production, NRL, net zero, renewables, CSR, the **DRIVE** digital programme, credit ratings) comes from these and cites them; non-official sources (reviews, news, analyst targets) were removed | **Implemented** (`data/company/oil_india.json`; a test fails if any source is not an official domain) |
| **data.gov.in** | NIC / MeitY | Government open data, incl. PPAC's *Monthly Indigenous Crude Oil Production* | Planned: official sector context (national production, OIL's share) for the assistant | **Not yet** — data.gov.in currently shows "Request API" for this dataset; will be added when its API is published |
| **API Setu** | MeitY | Government API platform; lists IMD weather APIs and DigiLocker | Planned: IMD rainfall to corroborate "rain" delay reasons in DPRs; DigiLocker/e-Pramaan identity for access requests | **Roadmap** — IMD and DigiLocker access need registration |
| **DGH National Data Repository (NDR)** | DGH, MoPNG | Subsurface E&P data: seismic, well, log, reservoir | — | **Not applicable** — SIH26122 is about construction-project schedules, not subsurface data |
| **eRTMAC** (OIL) | Oil India Limited | Real-time drilling monitoring and advisory centre | — | **Not applicable** — drilling operations, not project schedule linking; P2E Bridge complements OIL's digital estate alongside DRIVE |

## Why this matters
- **Data sovereignty:** project data stays on Oil India's servers; BHASHINI is a Government of India service, and the AIKosh on-premise path keeps even speech inside the company network.
- **Language reach for Assam field sites:** Assamese voice joins English, Hindi and Tamil.
- **Trustworthy answers:** company figures now match OIL's own annual report (this also corrected an earlier news-sourced figure).

## How to switch BHASHINI on
Cloud (register at bhashini.gov.in / ULCA, then):
```
BHASHINI_USER_ID=<your ULCA user id>
BHASHINI_ULCA_API_KEY=<your ULCA API key>
# optional: BHASHINI_PIPELINE_ID (default: MeitY public pipeline)
```
On-premise (AIKosh models behind a BHASHINI/Dhruva-compatible endpoint):
```
BHASHINI_INFERENCE_URL=http://<host>/services/inference/pipeline
BHASHINI_INFERENCE_KEY=<optional key>
BHASHINI_SERVICE_ASR=<service id>  BHASHINI_SERVICE_TRANSLATION=<service id>  BHASHINI_SERVICE_TTS=<service id>
```
Without these, the app reports `provider: browser` and uses the browser's speech engine.

## PPT slide text (copy-ready)
**Built on official resources**
- **BHASHINI (MeitY):** voice and translation in English, Hindi, Tamil and Assamese for the Time Agent and the assistant
- **AIKosh (IndiaAI):** IndicConformer and IndicTrans2 models for an on-premise, sovereign deployment
- **Oil India official data:** every company fact cited from OIL's Annual Report 2024-25 and oil-india.com; aligned with OIL's DRIVE digital programme
- **Next:** data.gov.in (PPAC production data) and API Setu (IMD weather to corroborate delay causes)
- *DGH NDR and eRTMAC were evaluated and are out of scope for SIH26122 (subsurface and drilling data)*

## Sources
- BHASHINI API documentation: https://bhashini.gitbook.io/bhashini-apis
- AIKosh model pages: https://aikosh.indiaai.gov.in/home/models/details/indic_trans2.html · https://aikosh.indiaai.gov.in/home/models/details/aibharat_indicconformer_600m_multi.html
- OIL Annual Report 2024-25: https://www.oil-india.com/files/financial_results_documents/OIL_India_Annual_Report_2024_25_0.pdf · Financial Results: https://www.oil-india.com/financial-results · Net Zero 2040: https://www.oil-india.com/sustainability/net-zero-2040 · CSR: https://www.oil-india.com/csr-oil
- data.gov.in dataset: https://www.data.gov.in/resource/monthly-indigenous-crude-oil-production
- API Setu: https://apisetu.gov.in/ · IMD API reference: https://api.imd.gov.in/public/api_reference.html
- DGH NDR: https://www.ndrdgh.gov.in/NDR/
