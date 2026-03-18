"use client";

import { useEffect, useRef, useState } from "react";
import { streamChat } from "../lib/api";

// ─── Types ────────────────────────────────────────────────────────────────────

type Role = "user" | "assistant";

interface Message {
  id: string;
  role: Role;
  text: string;
  streaming?: boolean;
}

type Step = 1 | 2 | 3;

const STEPS: { sublabel: string }[] = [
  { sublabel: "COMPLETION" },
  { sublabel: "VALIDATION" },
  { sublabel: "DONE" },
];

const RS_TABS = ["Input", "Preview", "ER", "Flow", "Data", "Gantt", "Quality", "Summary"] as const;
type RsTab = (typeof RS_TABS)[number];

// ─── Hardcoded RS preview data ─────────────────────────────────────────────────

const MOCK_RS = {
  title: "Requirements Specification",
  project: "Automated Sales Report System",
  version: "0.1 — Draft",
  date: "2026-03-18",
  sections: [
    {
      heading: "1. Project Overview",
      body: `The client requires an automated system that collects daily sales data from the existing CRM (Salesforce) and generates a consolidated PDF report distributed via email every morning at 07:00 CET.\n\nThe current process is entirely manual — a sales analyst spends approximately 2 hours each morning pulling data from multiple spreadsheets. The primary pain point is error-prone copy-paste and delayed delivery to management.`,
    },
    {
      heading: "2. Stakeholders",
      body: `• Product Owner: Head of Sales Operations\n• Primary Users: Sales Analysts (×3), Regional Managers (×8)\n• IT Contact: Infrastructure Team Lead\n• Sponsor: VP of Sales`,
    },
    {
      heading: "3. Functional Requirements",
      body: `FR-01  The system SHALL connect to Salesforce via REST API and extract the previous day's closed deals.\nFR-02  The system SHALL aggregate data by region, product line, and sales rep.\nFR-03  The system SHALL generate a PDF report using a predefined template.\nFR-04  The system SHALL deliver the report by email to a configurable recipient list by 07:00 CET.\nFR-05  The system SHALL send an alert email if the pipeline fails or data is unavailable.`,
    },
    {
      heading: "4. Non-Functional Requirements",
      body: `NFR-01  Performance: Report generation must complete within 3 minutes.\nNFR-02  Availability: The pipeline must succeed on ≥ 99% of business days.\nNFR-03  Security: Salesforce credentials must be stored in a secrets manager; no plain-text config.\nNFR-04  Maintainability: A non-developer must be able to update the recipient list without code changes.`,
    },
    {
      heading: "5. Out of Scope (MVP)",
      body: `• Real-time dashboards\n• Integration with ERP systems\n• Mobile application\n• Historical trend analysis beyond 90 days`,
    },
    {
      heading: "6. Open Questions",
      body: `[ ] Who approves the PDF template design?\n[ ] Is the Salesforce sandbox available for integration testing?\n[ ] What is the fallback if the 07:00 CET deadline is missed?`,
    },
  ],
};

// ─── Progress Tracker ─────────────────────────────────────────────────────────

function ProgressTracker({ currentStep }: { currentStep: Step }) {
  return (
    <div className="flex items-center justify-between px-6 pt-5 pb-3">
      {STEPS.map((step, i) => {
        const stepNum = (i + 1) as Step;
        const isActive = stepNum === currentStep;
        const isDone = stepNum < currentStep;
        return (
          <div key={step.sublabel} className="flex flex-1 items-start">
            {/* connector line (before every step except first) */}
            {i > 0 && (
              <div
                className={`mt-4 h-px flex-1 shrink-0 transition-colors ${
                  isDone ? "bg-[#4caf50]" : "bg-gray-200"
                }`}
              />
            )}
            <div className="flex flex-col items-center gap-1">
              <div
                className={`flex h-8 w-8 items-center justify-center rounded border-2 text-sm font-semibold transition-all ${
                  isActive
                    ? "border-[#4caf50] bg-white text-[#4caf50]"
                    : isDone
                    ? "border-[#4caf50] bg-[#4caf50] text-white"
                    : "border-gray-300 bg-white text-gray-400"
                }`}
              >
                {isDone ? (
                  <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                    <path d="M2 7l3.5 3.5L12 3.5" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                ) : (
                  stepNum
                )}
              </div>
              <span
                className={`text-[9px] font-semibold tracking-wide ${
                  isActive || isDone ? "text-[#4caf50]" : "text-gray-400"
                }`}
              >
                {step.sublabel}
              </span>
            </div>
            {/* connector line (after last step — invisible spacer) */}
            {i === STEPS.length - 1 && <div className="flex-1" />}
          </div>
        );
      })}
    </div>
  );
}

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

// ─── RS Preview ───────────────────────────────────────────────────────────────

function RsPreview({ content }: { content: typeof MOCK_RS | null }) {
  if (!content) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 text-center">
        <div className="h-px w-16 bg-gray-300" />
        <p className="text-base font-medium text-gray-400">Requirements Specification</p>
        <p className="text-sm text-gray-400">
          The document fills in automatically<br />during the conversation
        </p>
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto p-6">
      <div className="mx-auto max-w-3xl rounded bg-white p-8 shadow-sm">
        {/* Document header */}
        <div className="mb-6 border-b border-gray-100 pb-6">
          <h1 className="text-2xl font-bold text-gray-900">{content.title}</h1>
          <div className="mt-2 flex flex-wrap gap-4 text-sm text-gray-500">
            <span><span className="font-medium text-gray-700">Project:</span> {content.project}</span>
            <span><span className="font-medium text-gray-700">Version:</span> {content.version}</span>
            <span><span className="font-medium text-gray-700">Date:</span> {content.date}</span>
          </div>
        </div>
        {/* Sections */}
        <div className="space-y-6">
          {content.sections.map((s) => (
            <div key={s.heading}>
              <h2 className="mb-2 text-sm font-bold uppercase tracking-wide text-[#1a3a2a]">{s.heading}</h2>
              <p className="whitespace-pre-wrap text-sm leading-relaxed text-gray-700">{s.body}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ─── RS Document Panel ────────────────────────────────────────────────────────

function RsDocumentPanel({
  activeTab,
  onTabChange,
  rsContent,
}: {
  activeTab: RsTab;
  onTabChange: (t: RsTab) => void;
  rsContent: typeof MOCK_RS | null;
}) {
  return (
    <div className="flex h-full flex-col">
      {/* Tab bar */}
      <div className="flex shrink-0 items-center border-b border-gray-200 bg-white px-4">
        <span className="mr-4 border-r border-gray-200 py-3 pr-4 text-sm font-semibold text-gray-800">
          Requirements Specification
        </span>
        <div className="flex">
          {RS_TABS.map((tab) => (
            <button
              key={tab}
              onClick={() => onTabChange(tab)}
              className={`px-3 py-3 text-sm transition-colors ${
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
          <RsPreview content={rsContent} />
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
  const [currentStep, setCurrentStep] = useState<Step>(1);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<RsTab>("Preview");
  // Start with mock data visible so the right panel is populated
  const [rsContent, setRsContent] = useState<typeof MOCK_RS | null>(MOCK_RS);

  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

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
    setCurrentStep((s) => (s < 2 ? 2 : s));

    addMessage("user", text);
    setIsStreaming(true);
    const assistantId = addMessage("assistant", "", true);

    let fullText = "";

    await streamChat(
      text,
      sessionId,
      (chunk) => {
        fullText += chunk;
        appendToMessage(assistantId, chunk);
      },
      (id) => setSessionId(id),
      () => {
        finalizeMessage(assistantId);
        setIsStreaming(false);

        const rsMatch = fullText.match(/```rs\n([\s\S]*?)```/);
        if (rsMatch || fullText.includes("[GENERATE_RS]")) {
          setCurrentStep(3);
          // In production, replace MOCK_RS with parsed content from the agent
          setRsContent(MOCK_RS);
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

  return (
    <div className="flex h-screen overflow-hidden bg-gray-100 font-sans">
      {/* ── Left panel ─────────────────────────────────── */}
      <div className="flex w-105 shrink-0 flex-col border-r border-gray-200 bg-white">
        {/* Header */}
        <div className="flex shrink-0 items-center justify-between border-b border-gray-200 px-4 py-3">
          <span className="text-sm font-bold text-gray-800">Document Preprocessor</span>
          <div className="flex items-center gap-3">
            <button className="flex items-center gap-1.5 rounded px-2 py-1 text-xs text-gray-500 hover:bg-gray-100">
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                <path d="M7 1l-6 5v7h4v-4h4v4h4V6z" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              Home
            </button>
            <div className={`h-3 w-3 rounded-full ${isStreaming ? "animate-pulse bg-yellow-400" : "bg-[#4caf50]"}`} />
          </div>
        </div>

        {/* Progress tracker */}
        <div className="shrink-0 border-b border-gray-100">
          <ProgressTracker currentStep={currentStep} />
          <div className="mx-6 mb-3 h-1 rounded-full bg-gray-100">
            <div
              className="h-1 rounded-full bg-[#4caf50] transition-all duration-500"
              style={{ width: `${((currentStep - 1) / 2) * 100}%` }}
            />
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
      </div>

      {/* ── Right panel ────────────────────────────────── */}
      <div className="flex flex-1 flex-col overflow-hidden">
        <RsDocumentPanel
          activeTab={activeTab}
          onTabChange={setActiveTab}
          rsContent={rsContent}
        />
      </div>
    </div>
  );
}
