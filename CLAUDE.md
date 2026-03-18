# CLAUDE.md — AI Business Consultant for Requirement Specification Generator

## Project Overview

This project is an **AI-powered Requirement Specification (RS) Generator** built for a hackathon. It guides non-technical business users through a structured conversational discovery process and automatically produces a standardized RS document.

The agent acts as an **Expert IT Business Consultant** — professional, patient, and jargon-free — taking users from a raw idea to a finalized, exportable specification document.

**Repository structure:**
```
/
├── frontend/    # Next.js chat UI, deployed to Vercel
└── backend/     # Google ADK agent, Vertex AI, PDF export
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Agent Orchestration | Google Agent Development Kit (ADK) |
| Core LLM | Gemini 1.5 Pro via Vertex AI |
| Knowledge Base / RAG | Vertex AI Search |
| File Storage (stretch) | Google Cloud Storage (GCS) |
| Frontend | Next.js (Vercel) |
| PDF Export | `reportlab` or `WeasyPrint` (Python, server-side) |
| Diagram Generation (stretch) | Mermaid.js |

---

## Agent Behavior & Persona

The agent must strictly follow this persona and workflow. Do not deviate.

### Persona Rules
- **Role:** Expert IT Business Consultant (business analyst, NOT a software architect).
- **Tone:** Professional, helpful, patient, and clear.
- **Do NOT** propose specific software architecture or write code for the user.
- **Do NOT** make IT decisions on behalf of the user.
- **Handle contradictions** by politely pointing them out and asking for clarification.
- **Stay on task** — gently redirect off-topic conversations back to the current RS chapter.

### Conversation Workflow

**Phase 1 — Initiation & Baseline Discovery**
1. Greet the user and explain the agent's purpose.
2. Ask about the **current state (As-Is)**: existing process and pain points.
3. Ask about the **ideal future state (To-Be)**: what success looks like.

**Phase 2 — Deep Dive: Requirements**
1. Systematically gather **Functional Requirements** (what the system must do).
2. Gather **Non-Functional Requirements** using business-friendly language (e.g., "How many people will use this at the same time?" instead of "concurrent users").
3. *(Stretch)* If a file is uploaded to GCS, analyze it and verify findings with the user.

**Phase 3 — Generation & Finalization**
1. Signal to the user that enough data has been collected.
2. Compile the RS document using the RAG template and chat history.
3. *(Stretch)* Generate a Mermaid.js flowchart of the To-Be process for user validation.
4. Enter a **review loop**: present the draft, accept feedback, and refine until approved.

---

## Implementation Task Plan

### Phase 1: Project Setup & Infrastructure
- [ ] **1.1** Set up GCP project and enable APIs (Vertex AI, Cloud Storage).
- [ ] **1.2** Initialize monorepo with `/frontend` and `/backend` directories.
- [ ] **1.3** Install and configure Google Agent Development Kit (ADK).
- [ ] **1.4** Initialize Next.js in `/frontend` and configure Vercel deployment.

### Phase 2: RAG Database Preparation
> ⚠️ Tasks 2.1 and 2.2 require **human input** and must run in parallel with Phase 1 to avoid blocking Phase 3.

- [ ] **2.1 [HUMAN]** Define all chapter/section names for the blank official RS template.
- [ ] **2.2 [HUMAN]** Gather and sanitize high-quality historical RS examples for few-shot learning.
- [ ] **2.3** Create and populate a Vertex AI Search datastore with the template and examples.

### Phase 3: Agent Core & Persona Engineering
- [ ] **3.1** Write the core system prompt: "Expert IT Business Consultant" persona + guardrails.
- [ ] **3.2** Configure ADK to route prompts to Gemini 1.5 Pro on Vertex AI.
- [ ] **3.3** Implement Phase 1 logic: greeting and Baseline Discovery (As-Is / To-Be).
- [ ] **3.4** Implement Phase 2 logic: systematic questioning for Functional and Non-Functional requirements.
- [ ] **3.5** Expose the ADK agent as a REST/streaming API endpoint for the frontend.

### Phase 4: Document Generation & Finalization Loop
- [ ] **4.1** Develop the compilation prompt: translate chat history + RAG context into the RS format.
- [ ] **4.2** Implement the review loop: present the draft and accept refinement requests.
- [ ] **4.3** Build PDF export using a server-side library (`reportlab` or `WeasyPrint`).

### Phase 5: MVP Frontend & Integration
- [ ] **5.1** Build the chat UI in Next.js (message thread, input box, streaming response support).
- [ ] **5.2** Connect the frontend to the ADK backend (handle streaming responses).
- [ ] **5.3** Implement the PDF download trigger and file delivery in the frontend.
- [ ] **5.4** Deploy to Vercel and validate full connectivity to the GCP backend.

### Phase 6: Testing
- [ ] **6.1 (Backend)** Unit tests for the compilation prompt — verify RS sections populate correctly from mock chat history.
- [ ] **6.2 (Backend)** Integration test for the full agent pipeline — scripted conversation end-to-end producing a valid RS document.
- [ ] **6.3 (Backend)** PDF export test — assert non-empty output with expected section headings.
- [ ] **6.4 (Frontend)** Component tests for the chat UI — message rendering, loading states, error states.
- [ ] **6.5 (E2E)** Smoke test with a sample use case (e.g., "automated sales report") from greeting to PDF download.

### Phase 7: Stretch Goals
- [ ] **7.1** Adjust the generation prompt to output Mermaid.js flowchart syntax.
- [ ] **7.2** Implement a frontend component to render Mermaid.js markdown natively in Next.js.
- [ ] **7.3** Configure a GCS bucket with upload handlers in the frontend.
- [ ] **7.4** Pass uploaded file URIs to Gemini for contextual vision/document parsing.

---

## Key Constraints & Notes

- **MVP is chat-first:** All initial context is gathered conversationally. No SharePoint ingestion in MVP (that is a production concern).
- **RAG is mandatory for document generation:** The agent must use Vertex AI Search to ground the RS output in the official template structure.
- **Gemini 1.5 Pro is the required model:** Do not substitute. Its large context window is critical for holding full conversation history during document generation.
- **ADK is mandatory:** It is the required orchestration framework for this hackathon. All agent routing, state, and tool integrations must go through ADK.
- **The agent does not make architecture decisions.** If a user asks the agent to choose a database, tech stack, or similar, redirect them back to defining business requirements.