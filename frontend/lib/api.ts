const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8080";

export interface ChatResponse {
  reply: string;
  session_id: string;
}

export interface DocumentResponse {
  markdown: string | null;
  ready: boolean;
}

export interface UploadedFile {
  filename: string;
  gcs_path: string;
}

/**
 * Send a message and stream the response via SSE.
 *
 * Callbacks:
 *   onChunk       — each text piece from the assistant
 *   onSessionId   — fires once with the session ID (first SSE event)
 *   onFinalizing  — fires when the backend detects ≥ 90% completeness and starts
 *                   the finalizer pipeline; the UI should show a "finalizing" state
 *   onFieldUpdate — fires mid-stream when the pre-stream quick extract detects a
 *                   newly filled (or changed) RS field. Lets the right panel fill
 *                   progressively before the agent's text reply arrives.
 *   onDone        — stream ended normally
 *   onError       — network or server error
 */
export async function streamChat(
  message: string,
  sessionId: string | null,
  onChunk: (text: string) => void,
  onSessionId: (id: string) => void,
  onDone: () => void,
  onError: (err: string) => void,
  onFinalizing?: () => void,
  onFieldUpdate?: (key: string, value: string) => void,
  directFields?: Record<string, string>,
  deferredFields?: string[],
): Promise<void> {
  const res = await fetch(`${API_URL}/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message,
      session_id: sessionId,
      ...(directFields ? { direct_fields: directFields } : {}),
      ...(deferredFields?.length ? { deferred_fields: deferredFields } : {}),
    }),
  });

  if (!res.ok || !res.body) {
    onError(`Server error: ${res.status}`);
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";

    for (const line of lines) {
      if (!line.startsWith("data: ")) continue;
      const payload = line.slice(6);
      if (payload === "[DONE]") {
        onDone();
        return;
      }
      try {
        const parsed = JSON.parse(payload);
        if (parsed.session_id) onSessionId(parsed.session_id);
        if (parsed.text) onChunk(parsed.text);
        if (parsed.event === "finalizing") onFinalizing?.();
        if (parsed.field_update && typeof parsed.field_update.key === "string") {
          onFieldUpdate?.(parsed.field_update.key, parsed.field_update.value ?? "");
        }
      } catch {
        // ignore malformed lines
      }
    }
  }

  onDone();
}

/**
 * Generate a Word doc from the 22 RSLiveTemplate fields, save to GCS, and trigger download.
 */
export async function downloadRsTemplateDocx(sessionId: string): Promise<void> {
  const res = await fetch(`${API_URL}/document/rs-template/docx`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId }),
  });

  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail?.detail ?? `Error ${res.status}`);
  }

  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "rs_template.docx";
  a.click();
  URL.revokeObjectURL(url);
}

/**
 * Trigger Word document download by posting to /document/docx and saving the blob.
 */
export async function downloadPdf(sessionId: string): Promise<void> {
  const res = await fetch(`${API_URL}/document/docx`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId }),
  });

  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail?.detail ?? `Error ${res.status}`);
  }

  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "requirement_specification.docx";
  a.click();
  URL.revokeObjectURL(url);
}

// ─── Live RS context extraction ───────────────────────────────────────────────

export interface RsSectionData {
  filled: boolean;
  value: string | null;
}

export interface RsPartialData {
  completeness: number;
  fields: Record<string, RsSectionData>;
}

/**
 * Directly set field values for a session, bypassing AI extraction.
 * These values are stored separately and survive subsequent AI extractions.
 * Returns the merged state (direct + AI) with updated completeness.
 */
export async function patchDirectFields(
  sessionId: string,
  fields: Record<string, string>,
): Promise<RsPartialData | null> {
  try {
    const res = await fetch(
      `${API_URL}/discovery/${encodeURIComponent(sessionId)}/fields`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ fields }),
      },
    );
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

/**
 * Fetch the last persisted 22-field discovery state for a session.
 * Used when loading a historical session to restore the Preview panel instantly
 * without re-running Gemini extraction.
 * Returns null on any failure so the caller keeps its current state.
 */
export async function getDiscoveryState(sessionId: string): Promise<RsPartialData | null> {
  try {
    const res = await fetch(`${API_URL}/discovery/${encodeURIComponent(sessionId)}`);
    if (!res.ok) return null;
    const data: RsPartialData = await res.json();
    // Treat completeness=0 with no fields as "nothing saved yet"
    if (data.completeness === 0 && Object.keys(data.fields).length === 0) return null;
    return data;
  } catch {
    return null;
  }
}

/**
 * After each AI turn, silently extract the current partial RS state from the session.
 * Returns null on any network/parse failure so the caller keeps the previous state.
 */
export async function extractContext(sessionId: string): Promise<RsPartialData | null> {
  try {
    const res = await fetch(`${API_URL}/context/extract`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId }),
    });
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

// ─── BPMN ─────────────────────────────────────────────────────────────────────

export interface BpmnResponse {
  ready: boolean;
  mermaid?: string;
  score?: number;
  missing?: string[];
}

/**
 * Ask the backend to check RS completeness and, if ≥ 90%, generate a
 * Mermaid BPMN diagram from the current session.
 */
export async function generateBpmn(sessionId: string): Promise<BpmnResponse> {
  const res = await fetch(`${API_URL}/bpmn/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId }),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail?.detail ?? `Error ${res.status}`);
  }
  return res.json();
}

// ─── DataFlow ─────────────────────────────────────────────────────────────────

export interface DataflowResponse {
  ready: boolean;
  mermaid?: string;
  score?: number;
  missing?: string[];
}

/**
 * Ask the backend to check DFD readiness and, if ≥ 70%, generate a
 * Mermaid Data Flow Diagram from the current session.
 */
export async function generateDataflow(sessionId: string): Promise<DataflowResponse> {
  const res = await fetch(`${API_URL}/dataflow/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId }),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail?.detail ?? `Error ${res.status}`);
  }
  return res.json();
}

/**
 * Upload a file to GCS via the backend, scoped to the given session folder.
 */
export async function uploadFile(
  file: File,
  sessionId: string,
  onProgress?: (percent: number) => void
): Promise<UploadedFile> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("session_id", sessionId);

  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_URL}/upload`);

    if (onProgress) {
      xhr.upload.addEventListener("progress", (e) => {
        if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100));
      });
    }

    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(JSON.parse(xhr.responseText));
      } else {
        const detail = (() => { try { return JSON.parse(xhr.responseText)?.detail; } catch { return null; } })();
        reject(new Error(detail ?? `Upload failed: ${xhr.status}`));
      }
    };

    xhr.onerror = () => reject(new Error("Network error during upload"));
    xhr.send(formData);
  });
}

/**
 * List files stored in GCS for a session.
 */
export async function getSessionUploads(sessionId: string): Promise<UploadedFile[]> {
  try {
    const res = await fetch(`${API_URL}/uploads/${encodeURIComponent(sessionId)}`);
    if (!res.ok) return [];
    const body: { session_id: string; files: UploadedFile[] } = await res.json();
    return body.files ?? [];
  } catch {
    return [];
  }
}

/**
 * Check whether the RS document is ready for a given session.
 */
export async function getDocument(sessionId: string): Promise<DocumentResponse> {
  const res = await fetch(`${API_URL}/document`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId }),
  });
  if (!res.ok) throw new Error(`Error ${res.status}`);
  return res.json();
}

// ─── Firestore SRS data ───────────────────────────────────────────────────────

export interface SrsData {
  session_id: string;
  updated_at: string | null;
  // Block 1 — Context & Business Problem
  s1_context: string | null;
  s1_business_problem: string | null;
  // Block 2 — Target State & Success
  s2_target_state: string | null;
  s2_success: string | null;
  // Block 3 — Scope & Boundaries
  s3_scope_in_out: string | null;
  s3_boundaries: string | null;
  // Block 4 — Data, Systems, Integrations & Access
  s4_data_systems: string | null;
  s4_integrations_access: string | null;
}

// ─── Conversation history ─────────────────────────────────────────────────────

export interface SessionSummary {
  session_id: string;
  updated_at: string | null;
  preview: string | null;
}

export interface HistoryMessage {
  role: "user" | "assistant";
  text: string;
  ts: string;
}

export async function getSessions(): Promise<SessionSummary[]> {
  try {
    const res = await fetch(`${API_URL}/sessions`);
    if (!res.ok) return [];
    return res.json();
  } catch {
    return [];
  }
}

export async function getHistory(sessionId: string): Promise<HistoryMessage[]> {
  try {
    const res = await fetch(`${API_URL}/history/${encodeURIComponent(sessionId)}`);
    if (!res.ok) return [];
    const body: { session_id: string; messages: HistoryMessage[] } = await res.json();
    return body.messages;
  } catch {
    return [];
  }
}

/**
 * Fetch the latest SRS data stored in Firestore for this session.
 * Returns null on any failure so callers can keep the previous state.
 */
export async function getFirestoreData(sessionId: string): Promise<SrsData | null> {
  try {
    const res = await fetch(`${API_URL}/firestore/data/${encodeURIComponent(sessionId)}`);
    if (!res.ok) return null;
    const body: { session_id: string; data: SrsData | null } = await res.json();
    return body.data;
  } catch {
    return null;
  }
}

// ─── Final Analysis (Finalizer Agent output) ──────────────────────────────────
// TODO: align these types with FINAL_ANALYSIS_SCHEMA in backend/agent/finalizer_agent.py
//       and generate them automatically once the schema is stable.

export interface TechnologyRecommendation {
  primary: string;
  rationale: string;
  alternatives: string[];
  constraints: string[];
}

export interface TeamProfile {
  recommended_team_type: "internal" | "partner" | "vendor" | "mixed";
  skills_required: string[];
  rationale: string;
}

export interface PriorityTier {
  tier: "strategic" | "tactical" | "operational";
  score: number;           // 0–100
  scoring_rationale: string;
  priority_drivers: string[];
}

export interface RiskAndDependencies {
  risks: string[];
  dependencies: string[];
  open_questions: string[];
}

export interface FinalAnalysisMeta {
  session_id: string;
  finalized_at: string;
  model: string;
  discovery_completeness: number;
}

export interface FinalAnalysis {
  // All 22 form fields as collected and cleaned up by the finalizer
  // TODO: replace Record<string,string> with a typed interface once field names are locked
  use_case_form: Record<string, string | null>;
  technology_recommendation: TechnologyRecommendation;
  team_profile: TeamProfile;
  priority_tier: PriorityTier;
  risk_and_dependencies: RiskAndDependencies;
  _meta: FinalAnalysisMeta;
}

export type AnalysisStatus = "not_found" | "pending" | "complete";

export interface AnalysisResponse {
  status: AnalysisStatus;
  analysis?: FinalAnalysis;
}

/**
 * Poll GET /analyses/{sessionId} to check finalization status.
 * Returns the status and the analysis if complete.
 * Always resolves (never throws) so callers can poll safely.
 */
export async function getAnalysis(sessionId: string): Promise<AnalysisResponse> {
  try {
    const res = await fetch(`${API_URL}/analyses/${encodeURIComponent(sessionId)}`);
    if (!res.ok) return { status: "not_found" };
    return res.json();
  } catch {
    return { status: "not_found" };
  }
}
