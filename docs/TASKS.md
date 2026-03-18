# Implementation Task Plan

## Phase 1: Project Setup & Infrastructure

- [ ] **Task 1.1:** Set up the GCP Project and enable necessary APIs (Vertex AI, Cloud Storage, Discovery Engine). ⚠️ Manual step — see README.md for the list of APIs to enable.
- [x] **Task 1.2:** Initialize project repository and development environment (monorepo with `/frontend` and `/backend` directories).
- [x] **Task 1.3:** Install and configure Google Agent Development Kit (ADK). (google-adk v1.27.2 installed)
- [x] **Task 1.4:** Initialize Next.js project in `/frontend` and configure deployment to Vercel. (Next.js scaffolded with TypeScript + Tailwind)

## Phase 2: RAG Database Preparation

> **Note: Tasks 2.1 and 2.2 require human input and must be completed in parallel with Phase 1 to avoid blocking Phase 3.**

- [ ] **Task 2.1 [HUMAN]:** Prepare the blank, official Requirement Specification (RS) template (define all chapter/section names).
- [ ] **Task 2.2 [HUMAN]:** Gather and sanitize high-quality historical RS examples for few-shot learning.
- [ ] **Task 2.3:** Create and populate a Vertex AI Search datastore with the template and examples.

## Phase 3: Agent Core & Persona Engineering

- [ ] **Task 3.1:** Write the core system prompt establishing the "Expert IT Business Consultant" persona and guardrails.
- [ ] **Task 3.2:** Configure the Google ADK to route prompts to Gemini 1.5 Pro on Vertex AI.
- [ ] **Task 3.3:** Implement Phase 1 logic: Initiation, greeting, and Baseline Discovery (As-is vs To-be).
- [ ] **Task 3.4:** Implement Phase 2 logic: Deep Dive systematic questioning for Functional and Non-Functional requirements.
- [ ] **Task 3.5:** Expose the ADK agent as a REST/streaming API endpoint for frontend consumption.

## Phase 4: Document Generation & Finalization Loop

- [ ] **Task 4.1:** Develop the compilation prompt: translate chat history and RAG context into the final RS document format.
- [ ] **Task 4.2:** Implement the review loop: present the draft to the user and accept refinement requests.
- [ ] **Task 4.3:** Build PDF export logic using a server-side library (e.g., `reportlab` or `WeasyPrint` in Python).

## Phase 5: MVP Frontend & Integration

- [ ] **Task 5.1:** Build the conversational chat UI in Next.js (message thread, input box, streaming response support).
- [ ] **Task 5.2:** Connect the Next.js frontend to the Vertex AI ADK backend via API calls (handle streaming).
- [ ] **Task 5.3:** Implement the PDF download trigger and file delivery in the frontend.
- [ ] **Task 5.4:** Deploy frontend to Vercel and validate connectivity to the GCP backend.

## Phase 6: Testing

- [ ] **Task 6.1 (Backend):** Unit tests for the compilation prompt logic — verify RS sections are correctly populated from mock chat history.
- [ ] **Task 6.2 (Backend):** Integration test for the full agent pipeline — run a scripted conversation end-to-end and assert a valid RS document is produced.
- [ ] **Task 6.3 (Backend):** Test PDF export — assert the generated PDF is non-empty and contains expected section headings.
- [ ] **Task 6.4 (Frontend):** Component tests for the chat UI — message rendering, loading states, and error states.
- [ ] **Task 6.5 (E2E):** Smoke test with a sample use case (e.g., "automated sales report") covering the full flow from greeting to PDF download.

## Phase 7: Nice-to-Have Features (Stretch Goals)

- [ ] **Task 7.1 (Diagrams):** Adjust the generation prompt to include Mermaid.js flowchart syntax.
- [ ] **Task 7.2 (Diagrams):** Implement a frontend component to render Mermaid.js markdown natively in Next.js.
- [ ] **Task 7.3 (Files):** Configure a GCS bucket with upload handlers for the frontend.
- [ ] **Task 7.4 (Files):** Pass uploaded file URIs to the Gemini model for contextual vision/document parsing.
