# AILVN Technical Guide for Presentation and Q&A

This document is a practical walkthrough of the current AILVN implementation so you can explain the system clearly during demos, viva, and technical Q&A.

---

## 1) What AILVN Is

AILVN (AI powered Laya Voice Navigator) is an AI-assisted insurance support platform that:

- verifies caller identity from policyholder records,
- classifies caller intent,
- retrieves policy/member context (RAG-style),
- generates response text from templates,
- optionally speaks responses via TTS,
- supports live simulator testing in the web UI.

It includes:

- a **landing page** with Call entry,
- a **call simulator** (chat + talk mode),
- **admin/portal APIs** for templates and operations,
- **Cosmos DB-backed data** (policyholders, templates, call events).

---

## 2) High-Level Architecture

Request flow (simulator path):

1. User opens `/app` landing page and clicks **Call**.
2. User selects a policyholder in simulator.
3. App rings, then auto-connects to Talk Mode.
4. Voice/text input is sent to `/simulate`.
5. Backend extracts identity fields (member ID, DOB, email as available).
6. Identity is verified against Cosmos (with fallback data if needed).
7. Intent is resolved (service + local rules).
8. Member + policy context is gathered.
9. A rendered response template is returned.
10. Frontend displays response and may play TTS.

Data/services used:

- **Azure Cosmos DB**: policyholders, templates, logs
- **Azure AI Search / KB retriever path**: policy clause retrieval
- **OpenAI/Azure OpenAI/local LLM options**: intent pipeline paths
- **FastAPI**: REST + websocket endpoints

---

## 3) Frontend Overview

Primary frontend files:

- `frontend/index.html`
- `frontend/css/style.css`
- `frontend/js/app.js`
- `frontend/js/simulator.js`
- `frontend/js/dashboard.js`

### 3.1 Landing

- Full-screen landing mode.
- Background image from `frontend/assets/laya-reception.jpg`.
- Text overlay:
  - Welcome to AILVN
  - AI powered Laya Voice Navigator
  - One stop solution for all your queries on policies
- `Call` button routes to simulator view.

### 3.2 Simulator

Simulator supports:

- policyholder selection (sets detected caller phone),
- chat mode and talk mode,
- continuous talk capture and response loop,
- hard stop behavior.

Recent reliability controls:

- **Hard Stop** cancels mic, ringing, TTS, and in-flight API/TTS calls.
- **Echo guard** reduces AI-voice re-capture.
- **Speech buffering** waits for a short pause before committing voice to backend.
- **Auto ring + auto connect** after policyholder selection.

---

## 4) Backend Overview

Core backend modules:

- `main.py` and `api/main.py`: app entrypoints and mounts
- `call_handler.py`: simulator endpoints
- `agents/tasks.py`: core per-turn pipeline logic
- `tools/identity_tool.py`: identity verification logic
- `portal/insurance_portal.py`, `portal/portal_routes.py`: template portal layer
- `database/cosmos_client.py`, `database/seed_data.py`: data access and seed

### 4.1 Simulator API behavior

`/simulate` receives:

- `caller_id`
- `caller_phone`
- `message`
- `conversation_history`
- `demo_mode`

Pipeline in `agents/tasks.py`:

1. Extract profile fields from current + previous user turns.
2. Verify identity.
3. If not verified:
   - prompt for missing identity fields, or
   - fail with identity failure response.
4. If verified:
   - resolve intent,
   - retrieve context data,
   - render response template,
   - return text + metadata.

---

## 5) Identity Verification (Critical for Q&A)

Main file: `tools/identity_tool.py`

Verification accepts combinations:

- member_id + DOB,
- email + DOB,
- member_id + phone,
- optional security answers (if collected).

### 5.1 Robust ID handling

Important recent improvements:

- tolerant ID matching across record aliases:
  - `member_id`
  - `mem_id`
  - `policy_number`
  - `id`
- case/format-insensitive comparison.

### 5.2 Robust extraction from spoken input

Main file: `agents/tasks.py`

Parser now normalizes:

- `p o l 001` -> `POL-001`
- spacing/symbol variants (e.g., `POL 001`, `pol/001`) -> `POL-001`
- DOB variants like `1985 03 14`, `1985/03/14`, `1985-03-14` -> `1985-03-14`
- spoken number words mapped to digits (zero/one/etc.) before parsing.

Why this matters:

- STT often inserts spaces or punctuation unpredictably.
- Robust canonicalization prevents false verification failures.

---

## 6) Intent + Response Strategy

Intent sources:

- external intent service (if configured),
- internal heuristic fallback in `agents/tasks.py`.

Response generation:

- Uses template rendering pipeline (`portal` + template data).
- Templates are intended to be data-driven via Cosmos and seed JSON.
- RAG enrichment adds policy/member values to templates.

---

## 7) Data Layer

### 7.1 Policyholders

- Stored in Cosmos DB.
- Synthetic seeded users include `POL-001...` range plus profile fields.
- Includes verification-relevant fields:
  - member ID,
  - DOB,
  - phone/email,
  - optional security Q/A.

### 7.2 Templates

- Response templates loaded via portal service.
- CSR/small-talk seed JSON exists for bootstrap.
- Missing defaults can be upserted on startup or via portal endpoint.

---

## 8) Deployment Model

Current deployment pattern:

1. Build Docker image.
2. Push to ACR (`voicenavigatoracr1234.azurecr.io/voice-navigator:manual-latest`).
3. Update Azure Container App (`voice-orchestrator`).

Live base URL:

- `https://voice-orchestrator.ashybeach-01a35ca6.francecentral.azurecontainerapps.io`

Common validation endpoints:

- `/health`
- `/app/`

---

## 9) Demo Script (Short)

1. Open landing page.
2. Briefly explain one-line value proposition.
3. Click **Call**.
4. Select policyholder (ringing + auto-connect to Talk Mode).
5. Speak identity input: `POL-001, 1985-03-14`.
6. Confirm verification acknowledgement.
7. Ask a coverage/claims question.
8. Show AI response in chat + voice.
9. Click Stop to show hard-stop safety.
10. Mention portal/template/data-driven architecture.

---

## 10) Likely Q&A Answers

### Q: How do you prevent failed verification from speech noise?

A: We canonicalize identity text before verification. Member IDs and DOBs are normalized (case-insensitive, punctuation-insensitive, whitespace-insensitive, with spoken number-word conversion) and matched against multiple ID aliases in records.

### Q: What if user says partial information first?

A: The system explicitly prompts for missing fields at the verification stage. It does not proceed to policy answers until verification succeeds.

### Q: How do you stop runaway voice loops?

A: Talk Mode includes hard-stop controls and cancellation logic for mic capture, ring timers, TTS playback, and in-flight network calls.

### Q: Is this template-based or fully generated?

A: Response output is template-driven with retrieved data values injected, giving consistency and compliance while still enabling intelligent routing.

### Q: What happens if Cosmos is unavailable?

A: There is a fallback demo dataset path for simulator continuity; production should use Cosmos for authoritative records.

### Q: How do you scale/deploy?

A: Containerized app on Azure Container Apps with ACR image versioning and revision-based rollouts.

---

## 11) Troubleshooting Cheatsheet

### Symptom: Identity fails for correct `POL-001 + DOB`

Check:

- input captured correctly in chat,
- parser normalization path (`agents/tasks.py`) is deployed,
- alias ID matching logic (`tools/identity_tool.py`) is deployed,
- expected policyholder exists in Cosmos/fallback data.

### Symptom: Stop button still talks

Check:

- hard-stop revision deployed,
- browser hard refresh (`Ctrl+F5`),
- no stale tab with older JS bundle.

### Symptom: Voice not captured

Check:

- browser mic permission allowed,
- secure origin (https),
- speech recognition support in browser,
- talk mode enabled and not blocked by active TTS.

---

## 12) Key Strengths to Highlight in Presentation

- End-to-end real-time conversational flow.
- Strong identity-gated response path.
- Data-driven templates and modular architecture.
- Practical simulator with voice, ring/connect behavior, and hard stop safety.
- Cloud-native deployment with observable health endpoints.

---

## 13) Quick File Map (for technical panel)

- UI routing/state: `frontend/js/app.js`
- Voice UX control loop: `frontend/js/simulator.js`
- Main simulator page markup: `frontend/index.html`
- Styling: `frontend/css/style.css`
- Turn pipeline: `agents/tasks.py`
- Identity logic: `tools/identity_tool.py`
- Cosmos access: `database/cosmos_client.py`
- Template portal: `portal/insurance_portal.py`, `portal/portal_routes.py`
- App bootstrap/routes: `main.py`, `api/main.py`

---

If needed, convert this into a slide deck outline with speaking notes in under 10 minutes.
