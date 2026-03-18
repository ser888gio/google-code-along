# AI Business Consultant — RS Generator

Monorepo for the AI-Assisted Requirement Specification Generator hackathon MVP.

## Structure

```
/
├── frontend/   # Next.js app, deployed to Vercel
├── backend/    # Python ADK agent + FastAPI, deployed to Vertex AI
└── docs/       # PLAN.md, TASKS.md
```

## Getting Started

### Backend

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env   # fill in your GCP values
uvicorn main:app --reload
```

### Frontend

```bash
cd frontend
npm install
cp .env.local.example .env.local   # fill in API URL
npm run dev
```

## GCP Prerequisites (Task 1.1 — Manual)

Enable the following APIs in your GCP project:
- Vertex AI API
- Cloud Storage API
- Discovery Engine API (for Vertex AI Search)
