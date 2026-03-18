const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface ChatResponse {
  reply: string;
  session_id: string;
}

export interface DocumentResponse {
  markdown: string | null;
  ready: boolean;
}

/**
 * Send a message and stream the response via SSE.
 * Calls onChunk for each text piece, onSessionId once with the session ID,
 * and onDone when the stream ends.
 */
export async function streamChat(
  message: string,
  sessionId: string | null,
  onChunk: (text: string) => void,
  onSessionId: (id: string) => void,
  onDone: () => void,
  onError: (err: string) => void
): Promise<void> {
  const res = await fetch(`${API_URL}/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, session_id: sessionId }),
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
      } catch {
        // ignore malformed lines
      }
    }
  }

  onDone();
}

/**
 * Trigger PDF download by posting to /document/pdf and saving the blob.
 */
export async function downloadPdf(sessionId: string): Promise<void> {
  const res = await fetch(`${API_URL}/document/pdf`, {
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
  a.download = "requirement_specification.pdf";
  a.click();
  URL.revokeObjectURL(url);
}

// ─── Live RS context extraction ───────────────────────────────────────────────

export interface RsSectionData {
  filled: boolean;
  content: string | null;
}

export type RsSectionKey =
  | "executive_summary"
  | "current_state"
  | "desired_future_state"
  | "scope"
  | "functional_requirements"
  | "non_functional_requirements"
  | "assumptions_and_constraints"
  | "open_questions";

export interface RsPartialData {
  completeness: number;
  sections: Record<RsSectionKey, RsSectionData>;
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

/**
 * Upload a file to GCS via the backend, scoped to the given session folder.
 */
export async function uploadFile(
  file: File,
  sessionId: string,
  onProgress?: (percent: number) => void
): Promise<{ gcs_path: string; filename: string }> {
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
