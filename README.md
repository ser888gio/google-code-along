# Discovery Agent — RS Generator

Monorepo for the AI-Assisted Requirement Specification Generator.

An interactive AI persona that guides business users through defining their needs and automatically generates coherent, standardized Requirement Specification (RS) documents, complete with auto-generated system diagrams.

## Features

- **Conversational Discovery:** Chat with an expert Discovery Agent (Google ADK + Gemini 2.5 Pro) to map out "As-Is" and "To-Be" specifications.
- **Live RS Template:** A sidebar panel tracks and fills all 22 RS fields across 6 sections in real time as the conversation progresses.
- **Automated Diagramming:** Generates BPMN and Dataflow diagrams from conversational context, rendered client-side with Mermaid.js.
- **Document Export:** Compiles the session into standard PDF and Word (DOCX) outputs.
- **Firestore Persistence:** Session state and RS fields are synced continuously to Firestore so progress survives page reloads.
- **Document Uploads:** Upload source documents to Google Cloud Storage for multimodal context extraction via Gemini.

## Structure

```text
/
├── frontend/                              # Next.js app — React, Tailwind CSS, Mermaid.js
│   └── app/
│       ├── components/RsLiveTemplate.tsx  # live RS sidebar component
│       └── generated/rsSchema.ts         # AUTO-GENERATED — do not edit by hand
├── backend/                              # Python — Google ADK, FastAPI, Gemini API
│   ├── field_schema.py                   # canonical RS field definitions (single source of truth)
│   └── scripts/generate_frontend_schema.py  # regenerates frontend/app/generated/rsSchema.ts
└── docs/                                 # project planning documents
```

## RS Field Schema

All 22 RS fields (across 6 sections) are defined once in `backend/field_schema.py`. The frontend TypeScript types and constants are generated from this file — **never edit `frontend/app/generated/rsSchema.ts` by hand**.

To regenerate after changing `field_schema.py`:

```bash
cd backend
.venv/Scripts/python scripts/generate_frontend_schema.py   # Windows
# .venv/bin/python scripts/generate_frontend_schema.py    # Mac/Linux
```

## Getting Started

### Prerequisites

Enable the following APIs in your GCP project:

- Cloud Storage API
- Firestore API
- Gemini API (via `GOOGLE_API_KEY`)

### Backend

The backend requires Python 3.12. Always use the project's virtual environment — never the global interpreter.

```bash
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # Windows
# .venv/bin/python -m pip install -r requirements.txt    # Mac/Linux

cp .env.example .env   # fill in GOOGLE_API_KEY, GCS bucket, Firestore project, etc.

.venv/Scripts/python -m uvicorn main:app --reload
```

### Frontend

```bash
cd frontend
npm install
cp .env.local.example .env.local   # fill in NEXT_PUBLIC_API_URL and NEXT_PUBLIC_WS_URL
npm run dev
```

## Running Tests

**Backend:**

```bash
cd backend
.venv/Scripts/python -m pytest tests/
```

**Frontend:**

```bash
cd frontend
npm run test
```
