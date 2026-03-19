"use client";

import { useEffect, useRef, useState } from "react";
import { streamChat, extractContext, downloadPdf, getFirestoreData, getSessions, getHistory, RsPartialData, SrsData, SessionSummary } from "../lib/api";
import FileUpload from "./components/FileUpload";
import BpmnPanel from "./components/BpmnPanel";
import DataflowPanel from "./components/DataflowPanel";
import RsLiveTemplate from "./components/RsLiveTemplate";
import FirestoreSrsPanel from "./components/FirestoreSrsPanel";

// ─── Types ────────────────────────────────────────────────────────────────────

type Role = "user" | "assistant";

interface Message {
  id: string;
  role: Role;
  text: string;
  streaming?: boolean;
}

const RS_TABS = ["Preview", "BPMN", "Data", "Database", "Summary"] as const;
type RsTab = (typeof RS_TABS)[number];

// ─── Message Bubble ───────────────────────────────────────────────────────────

function MessageBubble({ msg }: { msg: Message }) {
  const isUser = msg.role === "user";

  if (isUser) {
    return (
      <div className="rounded border border-gray-200 bg-[#f5fdf5] px-4 py-3">
        <div className="mb-1 text-[11px] font-bold uppercase tracking-widest text-gray-500">VY</div>
        <div className="flex items-start gap-2">
          <svg className="mt-0.5 shrink-0 text-gray-400" width="14" height="16" viewBox="0 0 14 16" fill="none">
            <rect x="1" y="1" width="12" height="14" rx="1" stroke="currentColor" strokeWidth="1.5" />
            <path d="M3 5h8M3 8h8M3 11h5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
          <span className="text-sm text-gray-700">{msg.text}</span>
        </div>
      </div>
    );
  }

  return (
    <div className="rounded border border-gray-200 bg-white px-4 py-3">
      <div className="mb-1 text-[11px] font-bold uppercase tracking-widest text-gray-500">AI CONSULTANT</div>
      <p className="whitespace-pre-wrap text-sm text-gray-800">
        {msg.text}
        {msg.streaming && (
          <span className="ml-0.5 inline-block h-4 w-1.5 animate-[blink_1s_step-end_infinite] bg-gray-400 align-middle" />
        )}
      </p>
    </div>
  );
}

// ─── Error Card ───────────────────────────────────────────────────────────────

function ErrorCard({ message, onDismiss }: { message: string; onDismiss: () => void }) {
  return (
    <div className="rounded border border-red-200 bg-[#fff5f5] px-4 py-3">
      <div className="mb-1 flex items-center justify-between">
        <span className="text-[11px] font-bold uppercase tracking-widest text-red-600">ERROR</span>
        <button onClick={onDismiss} className="text-xs text-gray-400 hover:text-gray-600">✕</button>
      </div>
      <p className="text-sm text-red-700">{message}</p>
    </div>
  );
}

// ─── RS Document Panel ────────────────────────────────────────────────────────

function RsDocumentPanel({
  activeTab,
  onTabChange,
  rsPartial,
  sessionId,
  onGenerateFull,
  srsData,
}: {
  activeTab: RsTab;
  onTabChange: (t: RsTab) => void;
  rsPartial: RsPartialData | null;
  sessionId: string | null;
  onGenerateFull: () => void;
  srsData: SrsData | null;
}) {
  return (
    <div className="flex h-full flex-col">
      {/* Tab bar */}
      <div className="flex shrink-0 items-center border-b border-gray-200 bg-white px-4">
        <span className="mr-4 border-r border-gray-200 py-3 pr-4 text-sm font-semibold text-gray-800">
          Requirements Specification
        </span>
        <div className="flex overflow-x-auto">
          {RS_TABS.map((tab) => (
            <button
              key={tab}
              onClick={() => onTabChange(tab)}
              className={`whitespace-nowrap px-3 py-3 text-sm transition-colors ${
                activeTab === tab
                  ? "border-b-2 border-[#1a3a2a] bg-[#1a3a2a] text-white"
                  : "text-gray-500 hover:text-gray-800"
              }`}
            >
              {tab}
            </button>
          ))}
        </div>
      </div>

      {/* Content area */}
      <div className="flex-1 overflow-hidden bg-gray-50">
        {activeTab === "Preview" ? (
          <RsLiveTemplate rsPartial={rsPartial} onGenerateFull={onGenerateFull} />
        ) : activeTab === "BPMN" ? (
          <BpmnPanel sessionId={sessionId} />
        ) : activeTab === "Data" ? (
          <DataflowPanel sessionId={sessionId} />
        ) : activeTab === "Database" ? (
          <FirestoreSrsPanel data={srsData} />
        ) : activeTab === "Summary" ? (
          <div className="flex h-full flex-col items-center justify-center gap-4">
            <button
              className="flex items-center gap-2 rounded bg-[#4a6659] px-5 py-2.5 text-sm font-semibold text-white transition-opacity hover:opacity-90"
            >
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                <path d="M7 1v8M4 6l3 3 3-3" stroke="white" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
                <path d="M1 10v1a2 2 0 002 2h8a2 2 0 002-2v-1" stroke="white" strokeWidth="1.8" strokeLinecap="round" />
              </svg>
              Download Requirements Specification
            </button>
          </div>
        ) : (
          <div className="flex h-full items-center justify-center text-sm text-gray-400">
            {activeTab} — not yet available
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<RsTab>("Preview");
  const [rsPartial, setRsPartial] = useState<RsPartialData | null>(null);
  const [srsData, setSrsData] = useState<SrsData | null>(null);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historySessions, setHistorySessions] = useState<SessionSummary[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);

  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  // Stale-response guard: discard extraction results from earlier turns
  const extractNonceRef = useRef(0);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, [input]);

  function addMessage(role: Role, text: string, streaming = false): string {
    const id = crypto.randomUUID();
    setMessages((prev) => [...prev, { id, role, text, streaming }]);
    return id;
  }

  function appendToMessage(id: string, chunk: string) {
    setMessages((prev) =>
      prev.map((m) => (m.id === id ? { ...m, text: m.text + chunk } : m))
    );
  }

  function finalizeMessage(id: string) {
    setMessages((prev) =>
      prev.map((m) => (m.id === id ? { ...m, streaming: false } : m))
    );
  }

  async function handleSend() {
    const text = input.trim();
    if (!text || isStreaming) return;

    setInput("");
    setError(null);

    addMessage("user", text);
    setIsStreaming(true);
    const assistantId = addMessage("assistant", "", true);

    // Capture the session ID synchronously from the SSE stream.
    // React's sessionId state may still be null on the first turn when onDone fires.
    let capturedSessionId = sessionId;

    await streamChat(
      text,
      sessionId,
      (chunk) => {
        appendToMessage(assistantId, chunk);
      },
      (id) => {
        capturedSessionId = id;
        setSessionId(id);
      },
      async () => {
        finalizeMessage(assistantId);
        setIsStreaming(false);

        // Progressive RS fill — fire and forget; chat never blocks on this
        if (capturedSessionId) {
          const nonce = ++extractNonceRef.current;
          const [partial, fsData] = await Promise.all([
            extractContext(capturedSessionId),
            getFirestoreData(capturedSessionId),
          ]);
          // Only apply if a newer turn hasn't already superseded this one
          if (nonce === extractNonceRef.current) {
            if (partial) setRsPartial(partial);
            if (fsData) setSrsData(fsData);
          }
        }
      },
      (err) => {
        finalizeMessage(assistantId);
        setError(err);
        setIsStreaming(false);
      }
    );
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  async function handleGenerateFull() {
    if (!sessionId) return;
    try {
      await downloadPdf(sessionId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to generate document");
    }
  }

  async function openHistory() {
    setHistoryOpen(true);
    setHistoryLoading(true);
    const sessions = await getSessions();
    setHistorySessions(sessions);
    setHistoryLoading(false);
  }

  async function loadSession(sid: string) {
    const msgs = await getHistory(sid);
    setMessages(
      msgs.map((m) => ({ id: crypto.randomUUID(), role: m.role, text: m.text }))
    );
    setSessionId(sid);
    setRsPartial(null);
    setSrsData(null);
    setHistoryOpen(false);
  }

  function newConversation() {
    setMessages([]);
    setSessionId(null);
    setRsPartial(null);
    setSrsData(null);
    setHistoryOpen(false);
  }

  return (
    <div className="flex h-screen overflow-hidden bg-gray-100 font-sans">
      {/* ── Left panel ─────────────────────────────────── */}
      <div className="flex w-1/2 shrink-0 flex-col border-r border-gray-200 bg-white">
        {/* History sidebar */}
        {historyOpen && (
          <div className="absolute inset-0 z-40 flex">
            <div className="flex w-72 flex-col border-r border-gray-200 bg-white shadow-xl">
              <div className="flex shrink-0 items-center justify-between border-b border-gray-200 px-4 py-3">
                <span className="text-sm font-bold text-gray-800">Conversations</span>
                <button onClick={() => setHistoryOpen(false)} className="text-xs text-gray-400 hover:text-gray-600">✕</button>
              </div>
              <div className="shrink-0 border-b border-gray-200 p-3">
                <button
                  onClick={newConversation}
                  className="w-full rounded border border-dashed border-gray-300 py-2 text-xs font-semibold text-gray-500 hover:border-[#4caf50] hover:text-[#4a6659] transition-colors"
                >
                  + New conversation
                </button>
              </div>
              <div className="flex-1 overflow-y-auto">
                {historyLoading ? (
                  <p className="p-4 text-center text-xs text-gray-400">Loading…</p>
                ) : historySessions.length === 0 ? (
                  <p className="p-4 text-center text-xs text-gray-400">No past conversations found.</p>
                ) : (
                  historySessions.map((s) => (
                    <button
                      key={s.session_id}
                      onClick={() => loadSession(s.session_id)}
                      className={`w-full border-b border-gray-100 px-4 py-3 text-left hover:bg-gray-50 transition-colors ${s.session_id === sessionId ? "bg-[#f5fdf5]" : ""}`}
                    >
                      <p className="truncate text-xs font-medium text-gray-700">
                        {s.preview ?? s.session_id}
                      </p>
                      {s.updated_at && (
                        <p className="mt-0.5 text-[10px] text-gray-400">
                          {new Date(s.updated_at).toLocaleString()}
                        </p>
                      )}
                    </button>
                  ))
                )}
              </div>
            </div>
            <div className="flex-1 bg-black/20" onClick={() => setHistoryOpen(false)} />
          </div>
        )}

        {/* Header */}
        <div className="flex shrink-0 items-center justify-between border-b border-gray-200 px-4 py-3">
          <span className="text-sm font-bold text-gray-800">Document Preprocessor</span>
          <div className="flex items-center gap-3">
            <button
              onClick={openHistory}
              className="flex items-center gap-1.5 rounded px-2 py-1 text-xs text-gray-500 hover:bg-gray-100"
            >
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                <circle cx="7" cy="7" r="6" stroke="currentColor" strokeWidth="1.5" />
                <path d="M7 4v3.5l2 2" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              History
            </button>
            <div className={`h-3 w-3 rounded-full ${isStreaming ? "animate-pulse bg-yellow-400" : "bg-[#4caf50]"}`} />
          </div>
        </div>

        {/* Message thread */}
        <div className="flex-1 space-y-3 overflow-y-auto px-4 py-3">
          {messages.length === 0 && (
            <p className="pt-6 text-center text-xs text-gray-400">
              Start a conversation to build your specification.
            </p>
          )}
          {messages.map((msg) => (
            <MessageBubble key={msg.id} msg={msg} />
          ))}
          {error && <ErrorCard message={error} onDismiss={() => setError(null)} />}
          <div ref={bottomRef} />
        </div>

        {/* Input area */}
        <div className="shrink-0 border-t border-gray-200 p-3">
          <div className="flex items-end gap-2">
            <button
              onClick={() => setUploadOpen(true)}
              title="Attach a file"
              className="flex shrink-0 items-center justify-center rounded border border-gray-200 bg-white text-gray-500 hover:border-[#4caf50] hover:text-[#4caf50] transition-colors"
              style={{ width: 40, height: 40 }}
            >
              <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
                <path d="M9 4v10M4 9h10" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
              </svg>
            </button>
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Describe your project or answer the consultant's questions…"
              rows={1}
              disabled={isStreaming}
              className="flex-1 resize-none rounded border border-gray-200 bg-white px-3 py-2 text-sm text-gray-800 placeholder-gray-400 outline-none focus:border-[#4caf50] disabled:opacity-50"
              style={{ minHeight: 40, maxHeight: 160 }}
            />
            <button
              onClick={handleSend}
              disabled={!input.trim() || isStreaming}
              className="flex shrink-0 items-center gap-1.5 rounded bg-[#4a6659] px-4 py-2.5 text-sm font-semibold text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {isStreaming ? (
                <svg className="animate-spin" width="16" height="16" viewBox="0 0 24 24" fill="none">
                  <circle cx="12" cy="12" r="10" stroke="white" strokeWidth="3" strokeDasharray="31.4" strokeDashoffset="10" />
                </svg>
              ) : (
                <>
                  Send
                  <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                    <path d="M2 7h10M7 2l5 5-5 5" stroke="white" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </>
              )}
            </button>
          </div>
        </div>

        {/* File upload modal */}
        {uploadOpen && (
          <div
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
            onClick={() => setUploadOpen(false)}
          >
            <div
              className="w-80 rounded-lg border border-gray-200 bg-white p-5 shadow-xl"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="mb-3 flex items-center justify-between">
                <span className="text-sm font-semibold text-gray-800">Attach a file</span>
                <button
                  onClick={() => setUploadOpen(false)}
                  className="text-xs text-gray-400 hover:text-gray-600"
                >
                  ✕
                </button>
              </div>
              <FileUpload sessionId={sessionId} onUploaded={() => { setUploadOpen(false); }} />
            </div>
          </div>
        )}

        {/* Disclaimer */}
        <div className="shrink-0 px-4 py-1.5 text-center">
          <p className="text-[10px] text-gray-400">
            This is an AI system and cannot always be accurate. Please review outputs.
          </p>
        </div>
      </div>

      {/* ── Right panel ────────────────────────────────── */}
      <div className="flex w-1/2 flex-col overflow-hidden">
        <RsDocumentPanel
          activeTab={activeTab}
          onTabChange={setActiveTab}
          rsPartial={rsPartial}
          sessionId={sessionId}
          onGenerateFull={handleGenerateFull}
          srsData={srsData}
        />
      </div>
    </div>
  );
}
