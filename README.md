# AI Business Consultant — RS Generator

Monorepo for the AI-Assisted Requirement Specification Generator.

An interactive AI persona that guides business users through defining their needs and automatically generates coherent, standardized Requirement Specification (RS) documents, complete with auto-generated system diagrams.

## Features

- **Conversational Discovery:** Chat with an expert AI business consultant (Google ADK + Gemini 1.5 Pro) to map out "As-Is" and "To-Be" specifications.
- **Automated Diagramming:** Generates BPMN and Dataflow diagrams on the fly from conversational context using Mermaid.js.
- **Document Export:** Compiles the live session context into standard Document formats (PDF, Word).
- **Live Sync & Context:** Extracts core project context continuously and syncs document sections in real-time using Firestore.
- **Document Uploads:** Ingest specific user context by uploading source documents to Google Cloud Storage for multimodal processing.

## Structure

```text
/
├── frontend/   # Next.js 16 app with React 19, Tailwind CSS, & Mermaid
├── backend/    # Python FastAPI with Google ADK, agents, compilers, and diagrams
└── docs/       # Project planning and active to-do lists
```

## Getting Started

### Prerequisites

Enable the following APIs in your GCP project:

- Vertex AI API
- Cloud Storage API
- Discovery Engine API (for Vertex AI Search)
- Firestore API (if utilizing live document tracking)

### Backend

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env   # Fill in your GCP project details, GCS bucket out, etc.
uvicorn main:app --reload
```

### Frontend

```bash
cd frontend
npm install
cp .env.local.example .env.local   # Fill in NEXT_PUBLIC_API_URL
npm run dev
```

## Running Tests

There are extensive tests in both the backend and frontend.

**Backend tests:**

```bash
cd backend
pytest tests/
```

**Frontend tests:**

```bash
cd frontend
npm run test
```
