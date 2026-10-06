const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8080";

interface DocumentResponse {
	markdown: string | null;
	ready: boolean;
}

export interface UploadedFile {
	filename: string;
	gcs_path: string;
	sessionId?: string;
}

export type FeedbackVote = "up" | "down";
export type SessionRating = 1 | 2 | 3 | 4 | 5;

interface StreamChatCallbacks {
	onChunk: (text: string) => void;
	onSessionId: (id: string) => void;
	onDone: () => void;
	onError: (err: string) => void;
	onFinalizing?: () => void;
	onFieldUpdate?: (key: string, value: string) => void;
	onActiveField?: (key: string) => void;
	onMessageId?: (id: string) => void;
	onChoices?: (choices: string[]) => void;
	onTextReplace?: (text: string) => void;
}

function buildChatRequestBody(
	message: string,
	sessionId: string | null,
	directFields?: Record<string, string>,
	deferredFields?: string[],
): string {
	return JSON.stringify({
		message,
		session_id: sessionId,
		...(directFields ? { direct_fields: directFields } : {}),
		...(deferredFields?.length ? { deferred_fields: deferredFields } : {}),
	});
}

/** Dispatch a single parsed SSE event object. Returns true if the stream should stop. */
function dispatchSseEvent(
	parsed: Record<string, unknown>,
	callbacks: StreamChatCallbacks,
): boolean {
	// One event may carry several keys; the helpers run in this order on purpose.
	notifyIdentifiers(parsed, callbacks);
	if (parsed.error) {
		callbacks.onError(parsed.error as string);
		return true;
	}
	notifyTurnProgress(parsed, callbacks);
	notifyStructuredUpdates(parsed, callbacks);
	return false;
}

function notifyIdentifiers(
	parsed: Record<string, unknown>,
	callbacks: StreamChatCallbacks,
): void {
	if (parsed.session_id) callbacks.onSessionId(parsed.session_id as string);
	if (parsed.message_id) callbacks.onMessageId?.(parsed.message_id as string);
}

function notifyTurnProgress(
	parsed: Record<string, unknown>,
	callbacks: StreamChatCallbacks,
): void {
	if (parsed.text) callbacks.onChunk(parsed.text as string);
	if (parsed.event === "finalizing") callbacks.onFinalizing?.();
	if (typeof parsed.active_field === "string")
		callbacks.onActiveField?.(parsed.active_field);
}

function notifyStructuredUpdates(
	parsed: Record<string, unknown>,
	callbacks: StreamChatCallbacks,
): void {
	const update = parsed.field_update as
		| { key?: unknown; value?: string }
		| undefined;
	if (typeof update?.key === "string")
		callbacks.onFieldUpdate?.(update.key, update.value ?? "");
	if (Array.isArray(parsed.choices))
		callbacks.onChoices?.(parsed.choices as string[]);
	if (typeof parsed.text_replace === "string")
		callbacks.onTextReplace?.(parsed.text_replace);
}

function dispatchSsePayload(
	payload: string,
	callbacks: StreamChatCallbacks,
): boolean {
	if (payload === "[DONE]") {
		callbacks.onDone();
		return true;
	}

	try {
		const parsed = JSON.parse(payload) as Record<string, unknown>;
		return dispatchSseEvent(parsed, callbacks);
	} catch {
		return false;
	}
}

function dispatchSseLine(
	line: string,
	callbacks: StreamChatCallbacks,
): boolean {
	if (!line.startsWith("data: ")) return false;
	return dispatchSsePayload(line.slice(6), callbacks);
}

async function consumeSseStream(
	body: ReadableStream<Uint8Array>,
	callbacks: StreamChatCallbacks,
): Promise<void> {
	const reader = body.getReader();
	const decoder = new TextDecoder();
	let buffer = "";

	while (true) {
		const { done, value } = await reader.read();
		if (done) break;

		buffer += decoder.decode(value, { stream: true });
		const lines = buffer.split("\n");
		buffer = lines.pop() ?? "";

		for (const line of lines) {
			if (dispatchSseLine(line, callbacks)) return;
		}
	}

	callbacks.onDone();
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
	onActiveField?: (key: string) => void,
	onMessageId?: (id: string) => void,
	onChoices?: (choices: string[]) => void,
	onTextReplace?: (text: string) => void,
): Promise<void> {
	const res = await fetch(`${API_URL}/chat/stream`, {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: buildChatRequestBody(
			message,
			sessionId,
			directFields,
			deferredFields,
		),
	});

	if (!res.ok || !res.body) {
		onError(`Server error: ${res.status}`);
		return;
	}

	const callbacks: StreamChatCallbacks = {
		onChunk,
		onSessionId,
		onDone,
		onError,
		onFinalizing,
		onFieldUpdate,
		onActiveField,
		onMessageId,
		onChoices,
		onTextReplace,
	};

	await consumeSseStream(res.body, callbacks);
}

export async function submitFeedback(
	sessionId: string,
	messageId: string,
	vote: FeedbackVote,
	comment?: string,
): Promise<void> {
	const res = await fetch(`${API_URL}/feedback`, {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify({
			session_id: sessionId,
			message_id: messageId,
			vote,
			...(comment !== undefined ? { comment } : {}),
		}),
	});

	if (!res.ok) {
		const detail = await res.json().catch(() => ({}));
		throw new Error(detail?.detail ?? `Error ${res.status}`);
	}
}

export async function updateFeedbackComment(
	sessionId: string,
	messageId: string,
	comment: string,
): Promise<void> {
	const res = await fetch(
		`${API_URL}/feedback/${encodeURIComponent(messageId)}`,
		{
			method: "PATCH",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({
				session_id: sessionId,
				comment,
			}),
		},
	);

	if (!res.ok) {
		const detail = await res.json().catch(() => ({}));
		throw new Error(detail?.detail ?? `Error ${res.status}`);
	}
}

export async function submitSessionFeedback(
	sessionId: string,
	rating: SessionRating,
	comment?: string,
): Promise<void> {
	const res = await fetch(`${API_URL}/feedback/session`, {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify({
			session_id: sessionId,
			rating,
			...(comment !== undefined ? { comment } : {}),
		}),
	});

	if (!res.ok) {
		const detail = await res.json().catch(() => ({}));
		throw new Error(detail?.detail ?? `Error ${res.status}`);
	}
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
	a.style.display = "none";
	document.body.appendChild(a);
	a.click();
	document.body.removeChild(a);
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

type AcceptedSource =
	| "user_manual"
	| "user_direct_chat"
	| "user_accept_suggestion"
	| "user_upload"
	| "system_import";

export type FieldSource = AcceptedSource | "ai";

export interface RsField {
	value: string;
	filled: boolean;
	source: FieldSource | null;
	acceptedAt?: string | null;
	updatedAt: number;
	pendingSuggestion?: { value: string; receivedAt: number };
	dismissedSuggestions?: string[];
}

export interface RsState {
	fields: Record<string, RsField>;
	completeness: number;
}

interface RsAcceptedData {
	value: string;
	source: AcceptedSource;
	accepted_at?: string | null;
}

interface RsSuggestionData {
	value: string;
	source: "ai";
}

interface RsSectionData {
	status:
		| "empty"
		| "suggested"
		| "accepted"
		| "accepted_with_suggestion"
		| "deferred";
	accepted: RsAcceptedData | null;
	suggestion: RsSuggestionData | null;
	dismissed_suggestions?: string[];
	filled: boolean;
	value: string | null;
	source?: FieldSource | null;
}

export interface RsPartialData {
	completeness: number;
	accepted_completeness: number;
	discovery_completeness: number;
	fields: Record<string, RsSectionData>;
}

interface RsFieldStatePatch {
	action: "accept" | "dismiss" | "clear";
	fields?: Record<string, string>;
	keys?: string[];
	source?: AcceptedSource;
}

export async function patchRsFieldState(
	sessionId: string,
	patch: RsFieldStatePatch,
): Promise<RsPartialData | null> {
	try {
		const res = await fetch(
			`${API_URL}/discovery/${encodeURIComponent(sessionId)}/rs-field-state`,
			{
				method: "PATCH",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify(patch),
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
export async function getDiscoveryState(
	sessionId: string,
): Promise<RsPartialData | null> {
	try {
		const res = await fetch(
			`${API_URL}/discovery/${encodeURIComponent(sessionId)}`,
		);
		if (!res.ok) return null;
		const data: RsPartialData = await res.json();
		// Treat completeness=0 with no fields as "nothing saved yet"
		if (data.completeness === 0 && Object.keys(data.fields).length === 0)
			return null;
		return data;
	} catch {
		return null;
	}
}

/**
 * After each AI turn, silently extract the current partial RS state from the session.
 * Returns null on any network/parse failure so the caller keeps the previous state.
 */
export async function extractContext(
	sessionId: string,
): Promise<RsPartialData | null> {
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

interface BpmnResponse {
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

interface DataflowResponse {
	ready: boolean;
	mermaid?: string;
	score?: number;
	missing?: string[];
}

/**
 * Ask the backend to check DFD readiness and, if ≥ 70%, generate a
 * Mermaid Data Flow Diagram from the current session.
 */
export async function generateDataflow(
	sessionId: string,
): Promise<DataflowResponse> {
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
	onProgress?: (percent: number) => void,
): Promise<UploadedFile> {
	const formData = new FormData();
	formData.append("file", file);
	formData.append("session_id", sessionId);

	return new Promise((resolve, reject) => {
		const xhr = new XMLHttpRequest();
		xhr.open("POST", `${API_URL}/upload`);

		if (onProgress) {
			xhr.upload.addEventListener("progress", (e) => {
				if (e.lengthComputable)
					onProgress(Math.round((e.loaded / e.total) * 100));
			});
		}

		xhr.onload = () => {
			if (xhr.status >= 200 && xhr.status < 300) {
				resolve(JSON.parse(xhr.responseText));
			} else {
				const detail = (() => {
					try {
						return JSON.parse(xhr.responseText)?.detail;
					} catch {
						return null;
					}
				})();
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
export async function getDocument(
	sessionId: string,
): Promise<DocumentResponse> {
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

interface HistoryMessage {
	message_id?: string;
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
		const res = await fetch(
			`${API_URL}/history/${encodeURIComponent(sessionId)}`,
		);
		if (!res.ok) return [];
		const body: { session_id: string; messages: HistoryMessage[] } =
			await res.json();
		return body.messages;
	} catch {
		return [];
	}
}

/**
 * Fetch the latest SRS data stored in Firestore for this session.
 * Returns null on any failure so callers can keep the previous state.
 */
export async function getFirestoreData(
	sessionId: string,
): Promise<SrsData | null> {
	try {
		const res = await fetch(
			`${API_URL}/firestore/data/${encodeURIComponent(sessionId)}`,
		);
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

interface TechnologyRecommendation {
	primary: string;
	rationale: string;
	alternatives: string[];
	constraints: string[];
}

interface TeamProfile {
	recommended_team_type: "internal" | "partner" | "vendor" | "mixed";
	skills_required: string[];
	rationale: string;
}

interface PriorityTier {
	tier: "strategic" | "tactical" | "operational";
	score: number; // 0–100
	scoring_rationale: string;
	priority_drivers: string[];
}

interface RiskAndDependencies {
	risks: string[];
	dependencies: string[];
	open_questions: string[];
}

interface FinalAnalysisMeta {
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

type AnalysisStatus = "not_found" | "pending" | "complete";

interface AnalysisResponse {
	status: AnalysisStatus;
	analysis?: FinalAnalysis;
}

/**
 * Poll GET /analyses/{sessionId} to check finalization status.
 * Returns the status and the analysis if complete.
 * Always resolves (never throws) so callers can poll safely.
 */
export async function getAnalysis(
	sessionId: string,
): Promise<AnalysisResponse> {
	try {
		const res = await fetch(
			`${API_URL}/analyses/${encodeURIComponent(sessionId)}`,
		);
		if (!res.ok) return { status: "not_found" };
		return res.json();
	} catch {
		return { status: "not_found" };
	}
}
