"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { streamChat, extractContext, getDiscoveryState, downloadRsTemplateDocx, getFirestoreData, getSessions, getHistory, getAnalysis, getSessionUploads, patchDirectFields, submitFeedback, updateFeedbackComment, submitSessionFeedback, FeedbackVote, SessionRating, RsPartialData, SrsData, SessionSummary, FinalAnalysis, UploadedFile } from "../lib/api";
import { useAudioRecorder } from "../lib/useAudioRecorder";
import { useAudioPlayer } from "../lib/useAudioPlayer";
import { useWebSocket, WsServerMessage } from "../lib/useWebSocket";
import AnalysisPanel, { FinalizingOverlay } from "./components/AnalysisPanel";
import FileUpload from "./components/FileUpload";
import BpmnPanel from "./components/BpmnPanel";
import DataflowPanel from "./components/DataflowPanel";
import RsLiveTemplate from "./components/RsLiveTemplate";
import FirestoreSrsPanel from "./components/FirestoreSrsPanel";
import LanguageSwitcher from "./i18n/LanguageSwitcher";
import { useLocale } from "./i18n/LocaleContext";
import {
  DEFERRED_DIRECT_ANSWER_PATTERNS,
  DIRECT_CHAT_FIELD_PATTERNS,
  DirectChatFieldKey,
  STRICT_DIRECT_FIELD_KEYS,
  SUGGESTABLE_DIRECT_FIELD_KEYS,
} from "./generated/rsSchema";

// ─── Types ────────────────────────────────────────────────────────────────────

type Role = "user" | "assistant";

interface Message {
  id: string;
  role: Role;
  text: string;
  streaming?: boolean;
  messageId?: string;
  feedback?: {
    vote: FeedbackVote;
    comment?: string;
    pending?: boolean;
  };
}

const RS_TABS = ["Preview", "BPMN", "Data", "Database", "Analysis", "Summary"] as const;
type RsTab = (typeof RS_TABS)[number];

type ChatMode = "text" | "voice";
const SESSION_RATINGS = [1, 2, 3, 4, 5] as const satisfies readonly SessionRating[];

// Finalization can be in one of three states:
//   idle       — not yet triggered
//   finalizing — backend is running the finalizer pipeline; frontend is polling
//   complete   — final analysis is ready and stored in state
type FinalizingStatus = "idle" | "finalizing" | "complete";

// ─── Message Bubble ───────────────────────────────────────────────────────────

function MessageBubble({
  msg,
  sessionId,
  onFeedback,
  onFeedbackComment,
}: {
  msg: Message;
  sessionId: string | null;
  onFeedback: (localId: string, vote: FeedbackVote) => Promise<void>;
  onFeedbackComment: (localId: string, comment: string) => Promise<void>;
}) {
  const { t } = useLocale();
  const isUser = msg.role === "user";
  const [commentOpen, setCommentOpen] = useState(false);
  const [comment, setComment] = useState(msg.feedback?.comment ?? "");

  if (isUser) {
    return (
      <div className="rounded border border-gray-200 bg-[#f5fdf5] px-4 py-3">
        <div className="mb-1 text-[11px] font-bold uppercase tracking-widest text-gray-500">{t("label.you")}</div>
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

  const isThinking = msg.streaming && !msg.text;
  const canSendFeedback = Boolean(sessionId && msg.messageId && !msg.streaming);
  const feedbackPending = Boolean(msg.feedback?.pending);
  const activeVote = msg.feedback?.vote;

  async function handleVote(vote: FeedbackVote) {
    if (!canSendFeedback || feedbackPending) return;
    setCommentOpen(true);
    await onFeedback(msg.id, vote);
  }

  async function handleCommentSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!canSendFeedback || !activeVote || feedbackPending) return;
    await onFeedbackComment(msg.id, comment);
  }

  return (
    <div className="rounded border border-gray-200 bg-white px-4 py-3">
      <div className="mb-1 text-[11px] font-bold uppercase tracking-widest text-gray-500">{t("label.ai_consultant")}</div>
      {isThinking ? (
        <p className="text-sm italic text-gray-400">
          {t("thinking")}
          <span className="inline-flex gap-0.5 ml-0.5 align-middle">
            <span className="animate-[blink_1.2s_step-end_infinite] [animation-delay:0s]">.</span>
            <span className="animate-[blink_1.2s_step-end_infinite] [animation-delay:0.4s]">.</span>
            <span className="animate-[blink_1.2s_step-end_infinite] [animation-delay:0.8s]">.</span>
          </span>
        </p>
      ) : (
        <div className="text-sm text-gray-800 [&_p]:my-1 [&_p:first-child]:mt-0 [&_p:last-child]:mb-0 [&_ol]:my-1 [&_ol]:list-decimal [&_ol]:pl-5 [&_ul]:my-1 [&_ul]:list-disc [&_ul]:pl-5 [&_li]:my-0.5 [&_strong]:font-semibold [&_em]:italic [&_code]:rounded [&_code]:bg-gray-100 [&_code]:px-1 [&_code]:py-0.5 [&_code]:text-[0.85em] [&_a]:text-[#4a6659] [&_a]:underline [&_h1]:mt-2 [&_h1]:mb-1 [&_h1]:text-base [&_h1]:font-bold [&_h2]:mt-2 [&_h2]:mb-1 [&_h2]:text-sm [&_h2]:font-bold [&_h3]:mt-2 [&_h3]:mb-1 [&_h3]:text-sm [&_h3]:font-semibold">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.text}</ReactMarkdown>
          {msg.streaming && (
            <span className="ml-0.5 inline-block h-4 w-1.5 animate-[blink_1s_step-end_infinite] bg-gray-400 align-middle" />
          )}
        </div>
      )}
      {canSendFeedback && !isThinking && (
        <div className="mt-3 border-t border-gray-100 pt-2">
          <div className="flex items-center gap-1.5">
            <button
              type="button"
              aria-label={t("feedback.helpful")}
              title={t("feedback.helpful")}
              disabled={feedbackPending}
              onClick={() => void handleVote("up")}
              className={`flex h-7 w-7 items-center justify-center rounded border transition-colors ${
                activeVote === "up"
                  ? "border-[#4a6659] bg-[#edf5ef] text-[#1a3a2a]"
                  : "border-gray-200 text-gray-400 hover:border-gray-300 hover:text-gray-700"
              } ${feedbackPending ? "opacity-60" : ""}`}
            >
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                <path d="M7 10v10" />
                <path d="M15 5.5 14 10h5.5a2 2 0 0 1 2 2.3l-1.1 6a2 2 0 0 1-2 1.7H7V10l5-7a2 2 0 0 1 3 2.5Z" />
                <path d="M3 10h4v10H3z" />
              </svg>
            </button>
            <button
              type="button"
              aria-label={t("feedback.unhelpful")}
              title={t("feedback.unhelpful")}
              disabled={feedbackPending}
              onClick={() => void handleVote("down")}
              className={`flex h-7 w-7 items-center justify-center rounded border transition-colors ${
                activeVote === "down"
                  ? "border-red-300 bg-red-50 text-red-700"
                  : "border-gray-200 text-gray-400 hover:border-gray-300 hover:text-gray-700"
              } ${feedbackPending ? "opacity-60" : ""}`}
            >
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                <path d="M17 14V4" />
                <path d="M9 18.5 10 14H4.5a2 2 0 0 1-2-2.3l1.1-6a2 2 0 0 1 2-1.7H17v10l-5 7a2 2 0 0 1-3-2.5Z" />
                <path d="M21 14h-4V4h4z" />
              </svg>
            </button>
            {activeVote && (
              <button
                type="button"
                onClick={() => setCommentOpen((open) => !open)}
                className="ml-1 text-xs text-gray-500 hover:text-gray-800"
              >
                {commentOpen ? t("btn.hide_comment") : t("btn.add_comment")}
              </button>
            )}
          </div>
          {commentOpen && activeVote && (
            <form onSubmit={handleCommentSubmit} className="mt-2 flex gap-2">
              <textarea
                value={comment}
                onChange={(e) => setComment(e.target.value)}
                placeholder={t("feedback.optional_comment")}
                rows={2}
                className="min-h-16 flex-1 resize-y rounded border border-gray-200 px-3 py-2 text-sm text-gray-700 outline-none focus:border-[#4a6659] focus:ring-1 focus:ring-[#4a6659]"
              />
              <button
                type="submit"
                disabled={feedbackPending}
                className="h-8 self-end rounded bg-[#4a6659] px-3 text-xs font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-60"
              >
                {t("btn.save")}
              </button>
            </form>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Error Toast ──────────────────────────────────────────────────────────────

function ErrorToast({ message, onDismiss }: { message: string; onDismiss: () => void }) {
  const { t } = useLocale();
  useEffect(() => {
    const timer = setTimeout(onDismiss, 6000);
    return () => clearTimeout(timer);
  }, [message, onDismiss]);

  return (
    <div className="fixed bottom-6 right-6 z-50 flex max-w-sm items-start gap-3 rounded-lg border border-red-300 bg-white px-4 py-3 shadow-lg">
      <svg className="mt-0.5 shrink-0 text-red-500" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="10" />
        <line x1="12" y1="8" x2="12" y2="12" />
        <line x1="12" y1="16" x2="12.01" y2="16" />
      </svg>
      <div className="flex-1">
        <p className="text-[11px] font-bold uppercase tracking-widest text-red-600">{t("error.something_wrong")}</p>
        <p className="mt-0.5 text-sm text-gray-700">{message}</p>
      </div>
      <button onClick={onDismiss} className="shrink-0 text-gray-400 hover:text-gray-600">✕</button>
    </div>
  );
}

// ─── RS Document Panel ────────────────────────────────────────────────────────

function RsDocumentPanel({
  activeTab,
  onTabChange,
  rsPartial,
  directFields,
  onDirectFieldChange,
  sessionId,
  onGenerateFull,
  srsData,
  finalizingStatus,
  finalAnalysis,
  isExtracting,
}: {
  activeTab: RsTab;
  onTabChange: (t: RsTab) => void;
  rsPartial: RsPartialData | null;
  directFields: Record<string, string>;
  onDirectFieldChange: (key: string, value: string) => void;
  sessionId: string | null;
  onGenerateFull: () => void;
  srsData: SrsData | null;
  finalizingStatus: FinalizingStatus;
  finalAnalysis: FinalAnalysis | null;
  isExtracting: boolean;
}) {
  const { t } = useLocale();
  const TAB_LABELS: Record<string, string> = {
    Preview: t("tab.preview"),
    BPMN: t("tab.bpmn"),
    Data: t("tab.data"),
    Database: t("tab.database"),
    Analysis: t("tab.analysis"),
    Summary: t("tab.summary"),
  };

  return (
    <div className="flex h-full flex-col">
      {/* Tab bar */}
      <div className="flex shrink-0 items-center border-b border-gray-200 bg-white px-4">
        <span className="mr-4 border-r border-gray-200 py-3 pr-4 text-sm font-semibold text-gray-800">
          {t("header.rs")}
        </span>
        <div className="flex overflow-x-auto">
          {RS_TABS.map((tab) => (
            <button
              key={tab}
              onClick={() => onTabChange(tab)}
              className={`relative whitespace-nowrap px-3 py-3 text-sm transition-colors ${
                activeTab === tab
                  ? "border-b-2 border-[#1a3a2a] bg-[#1a3a2a] text-white"
                  : "text-gray-500 hover:text-gray-800"
              }`}
            >
              {TAB_LABELS[tab] ?? tab}
              {tab === "Analysis" && finalizingStatus === "finalizing" && (
                <span className="ml-1.5 inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-amber-400 align-middle" />
              )}
              {tab === "Analysis" && finalizingStatus === "complete" && (
                <span className="ml-1.5 inline-block h-1.5 w-1.5 rounded-full bg-[#4caf50] align-middle" />
              )}
            </button>
          ))}
        </div>
      </div>

      {/* Content area */}
      <div className="flex-1 overflow-hidden bg-gray-50">
        {activeTab === "Preview" ? (
          <RsLiveTemplate
            rsPartial={rsPartial}
            directFields={directFields}
            onGenerateFull={onGenerateFull}
            onDirectFieldChange={onDirectFieldChange}
            isExtracting={isExtracting}
          />
        ) : activeTab === "BPMN" ? (
          <BpmnPanel sessionId={sessionId} />
        ) : activeTab === "Data" ? (
          <DataflowPanel sessionId={sessionId} />
        ) : activeTab === "Database" ? (
          <FirestoreSrsPanel data={srsData} />
        ) : activeTab === "Analysis" ? (
          finalizingStatus === "complete" && finalAnalysis ? (
            <AnalysisPanel analysis={finalAnalysis} />
          ) : finalizingStatus === "finalizing" ? (
            <FinalizingOverlay />
          ) : (
            <div className="flex h-full items-center justify-center text-sm text-gray-400">
              {t("analysis.pending")}
            </div>
          )
        ) : activeTab === "Summary" ? (
          <div className="flex h-full flex-col items-center justify-center gap-4">
            <button
              className="flex items-center gap-2 rounded bg-[#4a6659] px-5 py-2.5 text-sm font-semibold text-white transition-opacity hover:opacity-90"
            >
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                <path d="M7 1v8M4 6l3 3 3-3" stroke="white" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
                <path d="M1 10v1a2 2 0 002 2h8a2 2 0 002-2v-1" stroke="white" strokeWidth="1.8" strokeLinecap="round" />
              </svg>
              {t("download.rs")}
            </button>
          </div>
        ) : (
          <div className="flex h-full items-center justify-center text-sm text-gray-400">
            {TAB_LABELS[activeTab] ?? activeTab}
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Constants ────────────────────────────────────────────────────────────────

function makeWelcomeMessage(text: string): Message {
  return { id: "welcome", role: "assistant", text, streaming: false };
}

// Fields that must never be AI-extracted (numeric/financial or file-backed).
const DIRECT_INPUT_KEYS = new Set<string>(STRICT_DIRECT_FIELD_KEYS);

// Fields the AI can suggest but only if the user hasn't typed a value yet.
const SUGGESTABLE_DIRECT_KEYS = new Set<string>(SUGGESTABLE_DIRECT_FIELD_KEYS);

function normalizeForMatch(value: string): string {
  return value
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

function inferDirectChatFieldFromAssistant(text: string): DirectChatFieldKey | null {
  const normalized = normalizeForMatch(text);
  for (const field of DIRECT_CHAT_FIELD_PATTERNS) {
    if (field.patterns.some((pattern) => new RegExp(pattern).test(normalized))) {
      return field.key;
    }
  }
  return null;
}

function isDeferredDirectAnswer(text: string): boolean {
  const normalized = normalizeForMatch(text);
  return DEFERRED_DIRECT_ANSWER_PATTERNS.some((pattern) =>
    new RegExp(pattern).test(normalized)
  );
}

function cleanDirectAnswerValue(text: string): string {
  return text
    .trim()
    .replace(/^(je to|it's|it is|jmenuje se|bude to)\s+/i, "")
    .replace(/[.。]+$/, "")
    .trim();
}

function isPlausibleDirectAnswer(text: string): boolean {
  const value = cleanDirectAnswerValue(text);
  return value.length > 0 && value.length <= 80 && !value.includes("\n") && !value.includes("?");
}

/**
 * Merge an AI-extracted partial state into the previous state, preserving
 * user-typed direct-input fields and suggestable fields that have been set.
 */
function mergePartialFields(
  prev: RsPartialData | null,
  incoming: RsPartialData,
  directFields: Record<string, string>,
): RsPartialData {
  return {
    completeness: incoming.completeness,
    fields: {
      ...incoming.fields,
      // Keep any field already marked filled (including SSE pre-fills)
      ...Object.fromEntries(
        Object.entries(prev?.fields ?? {}).filter(([, v]) => v.filled)
      ),
      // Preserve direct-input and user-typed suggestable fields
      ...Object.fromEntries(
        Object.entries(prev?.fields ?? {}).filter(
          ([k]) =>
            DIRECT_INPUT_KEYS.has(k) ||
            (SUGGESTABLE_DIRECT_KEYS.has(k) && (directFields[k] ?? "").trim() !== ""),
        )
      ),
    },
  };
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function ChatPage() {
  const { t } = useLocale();
  const [messages, setMessages] = useState<Message[]>(() => [makeWelcomeMessage(t("welcome_message"))]);
  const [input, setInput] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<RsTab>("Preview");
  const [rsPartial, setRsPartial] = useState<RsPartialData | null>(null);
  const [srsData, setSrsData] = useState<SrsData | null>(null);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [ratingOpen, setRatingOpen] = useState(false);
  const [sessionEnded, setSessionEnded] = useState(false);
  const [sessionRating, setSessionRating] = useState<SessionRating | null>(null);
  const [sessionRatingComment, setSessionRatingComment] = useState("");
  const [isSubmittingSessionRating, setIsSubmittingSessionRating] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historySessions, setHistorySessions] = useState<SessionSummary[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [finalizingStatus, setFinalizingStatus] = useState<FinalizingStatus>("idle");
  const [finalAnalysis, setFinalAnalysis] = useState<FinalAnalysis | null>(null);
  const [isExtracting, setIsExtracting] = useState(false);
  const [chatMode, setChatMode] = useState<ChatMode>("text");
  const [directFields, setDirectFields] = useState<Record<string, string>>({});
  const [deferredDirectFields, setDeferredDirectFields] = useState<DirectChatFieldKey[]>([]);
  const [activeWorkflowField, setActiveWorkflowField] = useState<string | null>(null);
  // Debounce timer ref for persisting direct fields to the backend
  const directFieldDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  // Stale-response guard: discard extraction results from earlier turns
  const extractNonceRef = useRef(0);
  // Polling interval ref — cleared when finalization completes or component unmounts
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);
  // Track the current voice transcription message id so we can append to it
  const voiceTranscriptIdRef = useRef<string | null>(null);
  // Track the current user voice transcription message id
  const voiceUserTranscriptIdRef = useRef<string | null>(null);
  // Track simple form fields the assistant just asked for so answers can fill instantly.
  const pendingDirectChatFieldRef = useRef<DirectChatFieldKey | null>(null);

  // ─── Audio Player ──────────────────────────────────────────────────────────
  const audioPlayer = useAudioPlayer();

  // ─── WebSocket ─────────────────────────────────────────────────────────────
  const handleWsAudio = useCallback(
    (pcmData: ArrayBuffer) => {
      audioPlayer.enqueue(pcmData);
    },
    [audioPlayer]
  );

  const handleWsMessage = useCallback(
    (msg: WsServerMessage) => {
      if (msg.type === "user_transcript") {
        // User voice input transcription — show as user chat bubble
        if (voiceUserTranscriptIdRef.current) {
          appendToMessage(voiceUserTranscriptIdRef.current, msg.text);
        } else {
          const id = addMessage("user", msg.text, true);
          voiceUserTranscriptIdRef.current = id;
        }
      } else if (msg.type === "text") {
        // Finalize the user transcript bubble when assistant starts responding
        if (voiceUserTranscriptIdRef.current) {
          finalizeMessage(voiceUserTranscriptIdRef.current);
          voiceUserTranscriptIdRef.current = null;
        }
        // Append transcription/text to the current assistant message or create one
        if (voiceTranscriptIdRef.current) {
          appendToMessage(voiceTranscriptIdRef.current, msg.text);
        } else {
          const id = addMessage("assistant", msg.text, true);
          voiceTranscriptIdRef.current = id;
        }
      } else if (msg.type === "turn_complete") {
        // Finalize any open user transcript bubble
        if (voiceUserTranscriptIdRef.current) {
          finalizeMessage(voiceUserTranscriptIdRef.current);
          voiceUserTranscriptIdRef.current = null;
        }
        // Finalize the assistant voice message
        if (voiceTranscriptIdRef.current) {
          finalizeMessage(voiceTranscriptIdRef.current);
          voiceTranscriptIdRef.current = null;
        }
        audioPlayer.drain();

        // Run the same post-processing as text chat: extract context + fetch Firestore data
        if (sessionId) {
          const nonce = ++extractNonceRef.current;
          setIsExtracting(true);
          Promise.all([
            extractContext(sessionId),
            getFirestoreData(sessionId),
          ]).then(([partial, fsData]) => {
            if (nonce === extractNonceRef.current) {
              if (partial) {
                setRsPartial((prev) => mergePartialFields(prev, partial, directFields));
                setDirectFields((prevDirect) => {
                  const updates: Record<string, string> = {};
                  for (const k of SUGGESTABLE_DIRECT_KEYS) {
                    if (!(prevDirect[k] ?? "").trim() && partial.fields[k]?.filled && partial.fields[k]?.value) {
                      updates[k] = partial.fields[k].value as string;
                    }
                  }
                  return Object.keys(updates).length ? { ...prevDirect, ...updates } : prevDirect;
                });
              }
              if (fsData) setSrsData(fsData);
              setIsExtracting(false);
            }
          }).catch((err) => {
            console.error("[Voice] Post-turn extraction failed:", err);
            if (nonce === extractNonceRef.current) {
              setIsExtracting(false);
            }
          });
        }

        // Handle finalization trigger from voice mode
        if (msg.finalizing) {
          setFinalizingStatus("finalizing");
          setActiveTab("Analysis");
        }
      } else if (msg.type === "error") {
        setError(msg.message);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [audioPlayer, sessionId]
  );

  const ws = useWebSocket({
    onAudioData: handleWsAudio,
    onMessage: handleWsMessage,
  });

  // ─── Audio Recorder ────────────────────────────────────────────────────────
  const handleAudioChunk = useCallback(
    (pcmData: ArrayBuffer) => {
      ws.sendAudio(pcmData);
    },
    [ws]
  );

  const audioRecorder = useAudioRecorder(handleAudioChunk);

  // Poll GET /analyses/{sessionId} every 5 s while the finalizer is running
  useEffect(() => {
    if (finalizingStatus !== "finalizing" || !sessionId) return;

    pollingRef.current = setInterval(async () => {
      const result = await getAnalysis(sessionId);
      if (result.status === "complete" && result.analysis) {
        clearInterval(pollingRef.current!);
        pollingRef.current = null;
        setFinalAnalysis(result.analysis);
        setFinalizingStatus("complete");
        setActiveTab("Analysis");
      }
    }, 5000);

    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current);
    };
  }, [finalizingStatus, sessionId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, [input]);

  useEffect(() => {
    if (!sessionId) return;
    refreshSessionUploads(sessionId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

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

  function setMessageBackendId(id: string, messageId: string) {
    setMessages((prev) =>
      prev.map((m) => (m.id === id ? { ...m, messageId } : m))
    );
  }

  async function handleFeedback(localId: string, vote: FeedbackVote) {
    const target = messages.find((m) => m.id === localId);
    if (!sessionId || !target?.messageId) return;

    const previousFeedback = target.feedback;
    setMessages((prev) =>
      prev.map((m) =>
        m.id === localId
          ? { ...m, feedback: { ...(m.feedback ?? {}), vote, pending: true } }
          : m
      )
    );

    try {
      await submitFeedback(sessionId, target.messageId, vote);
      setMessages((prev) =>
        prev.map((m) =>
          m.id === localId && m.feedback
            ? { ...m, feedback: { ...m.feedback, pending: false } }
            : m
        )
      );
    } catch (err) {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === localId ? { ...m, feedback: previousFeedback } : m
        )
      );
      setError(err instanceof Error ? err.message : "Could not save feedback");
    }
  }

  async function handleFeedbackComment(localId: string, comment: string) {
    const target = messages.find((m) => m.id === localId);
    if (!sessionId || !target?.messageId || !target.feedback?.vote) return;

    const previousComment = target.feedback.comment;
    setMessages((prev) =>
      prev.map((m) =>
        m.id === localId && m.feedback
          ? { ...m, feedback: { ...m.feedback, comment, pending: true } }
          : m
      )
    );

    try {
      await updateFeedbackComment(sessionId, target.messageId, comment);
      setMessages((prev) =>
        prev.map((m) =>
          m.id === localId && m.feedback
            ? { ...m, feedback: { ...m.feedback, pending: false } }
            : m
        )
      );
    } catch (err) {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === localId && m.feedback
            ? {
                ...m,
                feedback: {
                  ...m.feedback,
                  comment: previousComment,
                  pending: false,
                },
              }
            : m
        )
      );
      setError(err instanceof Error ? err.message : "Could not save feedback comment");
    }
  }

  function formatUploadAttachments(files: UploadedFile[]): string {
    return files.map((file) => file.gcs_path).join("\n");
  }

  async function refreshSessionUploads(sid: string, fallbackFiles: UploadedFile[] = []) {
    const files = await getSessionUploads(sid);
    const visibleFiles = files.length > 0 ? files : fallbackFiles;
    if (visibleFiles.length === 0) return;

    const attachments = formatUploadAttachments(visibleFiles);
    setDirectFields((prev) =>
      prev.attachments === attachments ? prev : { ...prev, attachments }
    );

    const merged = await patchDirectFields(sid, { attachments });
    if (merged) setRsPartial(merged);
  }

  async function handleFileUploaded(file: UploadedFile) {
    if (sessionId) {
      await refreshSessionUploads(sessionId, [file]);
    }
    setUploadOpen(false);
  }

  function handleDirectFieldChange(key: string, value: string) {
    setDirectFields((prev) => ({ ...prev, [key]: value }));
    if (value.trim()) {
      setDeferredDirectFields((prev) => prev.filter((field) => field !== key));
    }

    // Update completeness optimistically: re-read from backend after debounce
    if (directFieldDebounceRef.current) clearTimeout(directFieldDebounceRef.current);
    directFieldDebounceRef.current = setTimeout(async () => {
      if (!sessionId) return;
      const merged = await patchDirectFields(sessionId, { [key]: value });
      if (merged) {
        setRsPartial(merged);
      }
    }, 600);
  }

  function applyDirectChatAnswer(text: string): {
    directFieldsForRequest: Record<string, string>;
    deferredFieldsForRequest: DirectChatFieldKey[];
  } {
    const pendingKey = pendingDirectChatFieldRef.current;
    if (!pendingKey || (directFields[pendingKey] ?? "").trim()) {
      return {
        directFieldsForRequest: directFields,
        deferredFieldsForRequest: deferredDirectFields,
      };
    }

    pendingDirectChatFieldRef.current = null;
    if (isDeferredDirectAnswer(text) || !isPlausibleDirectAnswer(text)) {
      const nextDeferredFields = Array.from(new Set([...deferredDirectFields, pendingKey]));
      setDeferredDirectFields(nextDeferredFields);
      return {
        directFieldsForRequest: directFields,
        deferredFieldsForRequest: nextDeferredFields,
      };
    }

    const value = cleanDirectAnswerValue(text);
    const nextDirectFields = { ...directFields, [pendingKey]: value };
    const nextDeferredFields = deferredDirectFields.filter((field) => field !== pendingKey);
    setDirectFields(nextDirectFields);
    setDeferredDirectFields(nextDeferredFields);
    setRsPartial((prev) => ({
      completeness: prev?.completeness ?? 0,
      fields: {
        ...(prev?.fields ?? {}),
        [pendingKey]: { filled: true, value },
      },
    }));

    if (sessionId) {
      void patchDirectFields(sessionId, { [pendingKey]: value }).then((merged) => {
        if (merged) setRsPartial(merged);
      });
    }

    return {
      directFieldsForRequest: nextDirectFields,
      deferredFieldsForRequest: nextDeferredFields,
    };
  }

  async function handleSend() {
    const text = input.trim();
    if (!text || isStreaming || sessionEnded) return;

    setInput("");
    setError(null);
    const { directFieldsForRequest, deferredFieldsForRequest } = applyDirectChatAnswer(text);

    addMessage("user", text);
    setIsStreaming(true);
    const assistantId = addMessage("assistant", "", true);
    let assistantText = "";

    // Capture the session ID synchronously from the SSE stream.
    // React's sessionId state may still be null on the first turn when onDone fires.
    let capturedSessionId = sessionId;

    await streamChat(
      text,
      sessionId,
      (chunk) => {
        assistantText += chunk;
        appendToMessage(assistantId, chunk);
      },
      (id) => {
        capturedSessionId = id;
        setSessionId(id);
      },
      async () => {
        finalizeMessage(assistantId);
        setIsStreaming(false);
        pendingDirectChatFieldRef.current = inferDirectChatFieldFromAssistant(assistantText);

        // Progressive RS fill — fire and forget; chat never blocks on this
        if (capturedSessionId) {
          setIsExtracting(true);
          const nonce = ++extractNonceRef.current;
          const [partial, fsData] = await Promise.all([
            extractContext(capturedSessionId),
            getFirestoreData(capturedSessionId),
          ]);
          // Only apply if a newer turn hasn't already superseded this one
          if (nonce === extractNonceRef.current) {
            if (partial) {
              setRsPartial((prev) => mergePartialFields(prev, partial, directFieldsForRequest));
              setDirectFields((prevDirect) => {
                const updates: Record<string, string> = {};
                for (const k of SUGGESTABLE_DIRECT_KEYS) {
                  if (!(prevDirect[k] ?? "").trim() && partial.fields[k]?.filled && partial.fields[k]?.value) {
                    updates[k] = partial.fields[k].value as string;
                  }
                }
                return Object.keys(updates).length ? { ...prevDirect, ...updates } : prevDirect;
              });
            }
            if (fsData) setSrsData(fsData);
            setIsExtracting(false);
          }
        } else {
          setIsExtracting(false);
        }
      },
      (err) => {
        finalizeMessage(assistantId);
        setError(err);
        setIsStreaming(false);
        setIsExtracting(false);
      },
      // onFinalizing — backend has detected ≥ 90% completeness and started the pipeline
      () => {
        setFinalizingStatus("finalizing");
        setActiveTab("Analysis");
      },
      // onFieldUpdate — mid-stream field fill from the pre-stream quick extract
      // Skip financial direct-input fields. Suggestable fields pre-fill only if user hasn't typed.
      (key, value) => {
        if (DIRECT_INPUT_KEYS.has(key)) return;
        setRsPartial((prev) => ({
          completeness: prev?.completeness ?? 0,
          fields: {
            ...(prev?.fields ?? {}),
            [key]: { filled: true, value },
          },
        }));
        if (SUGGESTABLE_DIRECT_KEYS.has(key) && !(directFieldsForRequest[key] ?? "").trim()) {
          setDirectFields((prev) => ({ ...prev, [key]: value }));
          setDeferredDirectFields((prev) => prev.filter((field) => field !== key));
        }
      },
      directFieldsForRequest,
      deferredFieldsForRequest,
      (key) => setActiveWorkflowField(key),
      (messageId) => setMessageBackendId(assistantId, messageId),
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
      await downloadRsTemplateDocx(sessionId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to generate document");
    }
  }

  function openSessionRating() {
    if (!sessionId || isStreaming) return;
    if (chatMode === "voice") {
      audioRecorder.stopRecording();
      audioPlayer.stop();
      ws.disconnect();
      setChatMode("text");
    }
    setRatingOpen(true);
  }

  async function handleSessionRatingSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!sessionId || !sessionRating || isSubmittingSessionRating) return;

    setIsSubmittingSessionRating(true);
    try {
      await submitSessionFeedback(
        sessionId,
        sessionRating,
        sessionRatingComment,
      );
      setSessionEnded(true);
      setRatingOpen(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save session rating");
    } finally {
      setIsSubmittingSessionRating(false);
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
      msgs.map((m) => ({
        id: crypto.randomUUID(),
        role: m.role,
        text: m.text,
        messageId: m.message_id,
      }))
    );
    setSessionId(sid);
    setRsPartial(null);
    setSrsData(null);
    setFinalizingStatus("idle");
    setFinalAnalysis(null);
    setSessionEnded(false);
    setSessionRating(null);
    setSessionRatingComment("");
    setDirectFields({});
    setDeferredDirectFields([]);
    setActiveWorkflowField(null);
    setHistoryOpen(false);

    // Restore Preview panel and check for completed analysis in parallel
    const [savedDiscovery, analysisResult, fsData] = await Promise.all([
      getDiscoveryState(sid),
      getAnalysis(sid),
      getFirestoreData(sid),
    ]);
    if (savedDiscovery) {
      setRsPartial(savedDiscovery);
      // Restore direct fields from saved state
      const restored: Record<string, string> = {};
      for (const key of ["use_case_title", "department", "requestor", "product_owner",
        "saved_time_hours_per_year", "cost_saving", "revenue_increase", "comments", "attachments"]) {
        const entry = savedDiscovery.fields[key];
        if (entry?.filled && entry.value) restored[key] = entry.value;
      }
      setDirectFields(restored);
    }
    if (fsData) setSrsData(fsData);
    if (analysisResult.status === "complete" && analysisResult.analysis) {
      setFinalAnalysis(analysisResult.analysis);
      setFinalizingStatus("complete");
      setActiveTab("Analysis");
    }
  }

  function newConversation() {
    setMessages([makeWelcomeMessage(t("welcome_message"))]);
    setSessionId(null);
    setRsPartial(null);
    setSrsData(null);
    setDirectFields({});
    setDeferredDirectFields([]);
    setActiveWorkflowField(null);
    setFinalizingStatus("idle");
    setFinalAnalysis(null);
    setSessionEnded(false);
    setSessionRating(null);
    setSessionRatingComment("");
    setRatingOpen(false);
    setHistoryOpen(false);
    // Clean up voice mode if active
    if (chatMode === "voice") {
      audioRecorder.stopRecording();
      audioPlayer.stop();
      ws.disconnect();
      setChatMode("text");
    }
  }

  // ─── Voice mode handlers ───────────────────────────────────────────────────

  async function handleToggleVoice() {
    if (chatMode === "voice") {
      // Switching back to text mode
      audioRecorder.stopRecording();
      audioPlayer.stop();
      ws.disconnect();
      setChatMode("text");
      return;
    }

    // Switching to voice mode
    setChatMode("voice");

    // Ensure we have a session id (generate one if first interaction)
    const sid = sessionId ?? crypto.randomUUID();
    if (!sessionId) setSessionId(sid);

    // Initialize audio player (needs user gesture — this click counts)
    await audioPlayer.init();

    // Connect WebSocket
    ws.connect("default_user", sid);
  }

  async function handleMicToggle() {
    if (audioRecorder.isRecording) {
      audioRecorder.stopRecording();
    } else {
      // Stop any playback when user starts talking
      audioPlayer.stop();
      voiceTranscriptIdRef.current = null;
      await audioRecorder.startRecording();
    }
  }

  const isVoiceConnected = ws.connectionState === "connected";

  return (
    <div className="flex h-screen overflow-hidden bg-gray-100 font-sans">
      {/* ── Left panel ─────────────────────────────────── */}
      <div className="flex w-1/2 shrink-0 flex-col border-r border-gray-200 bg-white">
        {/* History sidebar */}
        {historyOpen && (
          <div className="absolute inset-0 z-40 flex">
            <div className="flex w-72 flex-col border-r border-gray-200 bg-white shadow-xl">
              <div className="flex shrink-0 items-center justify-between border-b border-gray-200 px-4 py-3">
                <span className="text-sm font-bold text-gray-800">{t("sidebar.conversations")}</span>
                <button onClick={() => setHistoryOpen(false)} className="text-xs text-gray-400 hover:text-gray-600">✕</button>
              </div>
              <div className="shrink-0 border-b border-gray-200 p-3">
                <button
                  onClick={newConversation}
                  className="w-full rounded border border-dashed border-gray-300 py-2 text-xs font-semibold text-gray-500 hover:border-[#4caf50] hover:text-[#4a6659] transition-colors"
                >
                  {t("btn.new_conversation")}
                </button>
              </div>
              <div className="flex-1 overflow-y-auto">
                {historyLoading ? (
                  <p className="p-4 text-center text-xs text-gray-400">{t("sidebar.loading")}</p>
                ) : historySessions.length === 0 ? (
                  <p className="p-4 text-center text-xs text-gray-400">{t("sidebar.no_conversations")}</p>
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
          <div className="flex items-center gap-2">
            <span className="text-sm font-bold text-gray-800">{t("header.title")}</span>
            {activeWorkflowField && (
              <span className="rounded border border-gray-200 bg-gray-50 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-gray-500">
                {activeWorkflowField.replace(/_/g, " ")}
              </span>
            )}
          </div>
          <div className="flex items-center gap-3">
            {/* Voice/Text mode toggle */}
            <button
              onClick={handleToggleVoice}
              title={chatMode === "voice" ? t("header.voice_to_text") : t("header.text_to_voice")}
              className={`flex items-center gap-1.5 rounded px-2 py-1 text-xs transition-colors ${
                chatMode === "voice"
                  ? "bg-red-50 text-red-600 hover:bg-red-100"
                  : "text-gray-500 hover:bg-gray-100"
              }`}
            >
              {chatMode === "voice" ? (
                <>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
                    <path d="M12 1a3 3 0 00-3 3v8a3 3 0 006 0V4a3 3 0 00-3-3z" fill="currentColor" />
                    <path d="M19 10v2a7 7 0 01-14 0v-2" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                    <path d="M12 19v4M8 23h8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                  </svg>
                  {t("btn.voice_mode")}
                </>
              ) : (
                <>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
                    <path d="M12 1a3 3 0 00-3 3v8a3 3 0 006 0V4a3 3 0 00-3-3z" stroke="currentColor" strokeWidth="2" />
                    <path d="M19 10v2a7 7 0 01-14 0v-2" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                    <path d="M12 19v4M8 23h8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                  </svg>
                  {t("btn.voice")}
                </>
              )}
            </button>
            <button
              onClick={openSessionRating}
              disabled={!sessionId || isStreaming || sessionEnded}
              className="flex items-center gap-1.5 rounded border border-gray-200 px-2 py-1 text-xs font-semibold text-gray-600 transition-colors hover:border-[#4a6659] hover:text-[#1a3a2a] disabled:cursor-not-allowed disabled:opacity-40"
            >
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                <path d="M3 3l8 8M11 3l-8 8" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
              </svg>
              {sessionEnded ? t("btn.ended") : t("btn.end_chat")}
            </button>
            <button
              onClick={openHistory}
              className="flex items-center gap-1.5 rounded px-2 py-1 text-xs text-gray-500 hover:bg-gray-100"
            >
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                <circle cx="7" cy="7" r="6" stroke="currentColor" strokeWidth="1.5" />
                <path d="M7 4v3.5l2 2" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              {t("btn.history")}
            </button>
            <LanguageSwitcher />
            <div className={`h-3 w-3 rounded-full ${
              chatMode === "voice"
                ? ws.connectionState === "connected"
                  ? audioRecorder.isRecording
                    ? "animate-pulse bg-red-500"
                    : "bg-blue-500"
                  : ws.connectionState === "connecting"
                    ? "animate-pulse bg-yellow-400"
                    : "bg-gray-400"
                : isStreaming
                  ? "animate-pulse bg-yellow-400"
                  : "bg-[#4caf50]"
            }`} />
          </div>
        </div>

        {/* Message thread */}
        <div className="flex-1 space-y-3 overflow-y-auto px-4 py-3">
          {messages.map((msg) => (
            <MessageBubble
              key={msg.id}
              msg={msg}
              sessionId={sessionId}
              onFeedback={handleFeedback}
              onFeedbackComment={handleFeedbackComment}
            />
          ))}
          <div ref={bottomRef} />
        </div>

        {/* Input area */}
        <div className="shrink-0 border-t border-gray-200 p-3">
          {chatMode === "voice" ? (
            /* Voice mode input */
            <div className="flex flex-col items-center gap-2">
              {/* Connection status */}
              {ws.connectionState === "connecting" && (
                <p className="text-xs text-yellow-600">{t("voice.connecting")}</p>
              )}
              {ws.connectionState === "error" && (
                <p className="text-xs text-red-600">{t("voice.conn_failed")}</p>
              )}
              {audioRecorder.error && (
                <p className="text-xs text-red-600">{audioRecorder.error}</p>
              )}

              <div className="flex items-center gap-3">
                {/* Mic button */}
                <button
                  onClick={handleMicToggle}
                  disabled={!isVoiceConnected || sessionEnded}
                  title={audioRecorder.isRecording ? "Stop speaking" : "Start speaking"}
                  className={`flex h-12 w-12 items-center justify-center rounded-full transition-all ${
                    audioRecorder.isRecording
                      ? "bg-red-500 text-white shadow-lg shadow-red-200 animate-pulse"
                      : isVoiceConnected && !sessionEnded
                        ? "bg-[#4a6659] text-white hover:opacity-90"
                        : "bg-gray-300 text-gray-500 cursor-not-allowed"
                  }`}
                >
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
                    <path d="M12 1a3 3 0 00-3 3v8a3 3 0 006 0V4a3 3 0 00-3-3z" fill="currentColor" />
                    <path d="M19 10v2a7 7 0 01-14 0v-2" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                    <path d="M12 19v4M8 23h8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                  </svg>
                </button>

                <span className="text-xs text-gray-500">
                  {audioRecorder.isRecording
                    ? t("voice.listening")
                    : audioPlayer.isPlaying
                      ? t("voice.ai_speaking")
                      : isVoiceConnected
                        ? sessionEnded ? t("voice.chat_ended") : t("voice.tap_to_speak")
                        : t("voice.connecting")}
                </span>
              </div>
            </div>
          ) : (
            /* Text mode input */
            <div className="flex items-end gap-2">
              <button
                onClick={() => setUploadOpen(true)}
                title="Attach a file"
                disabled={sessionEnded}
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
                placeholder={t("input.placeholder")}
                rows={1}
                disabled={isStreaming || sessionEnded}
                className="flex-1 resize-none rounded border border-gray-200 bg-white px-3 py-2 text-sm text-gray-800 placeholder-gray-400 outline-none focus:border-[#4caf50] disabled:opacity-50"
                style={{ minHeight: 40, maxHeight: 160 }}
              />
              <button
                onClick={handleSend}
                disabled={!input.trim() || isStreaming || sessionEnded}
                className="flex shrink-0 items-center gap-1.5 rounded bg-[#4a6659] px-4 py-2.5 text-sm font-semibold text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
              >
                {isStreaming ? (
                  <svg className="animate-spin" width="16" height="16" viewBox="0 0 24 24" fill="none">
                    <circle cx="12" cy="12" r="10" stroke="white" strokeWidth="3" strokeDasharray="31.4" strokeDashoffset="10" />
                  </svg>
                ) : (
                  <>
                    {t("btn.send")}
                    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                      <path d="M2 7h10M7 2l5 5-5 5" stroke="white" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  </>
                )}
              </button>
            </div>
          )}
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
                <span className="text-sm font-semibold text-gray-800">{t("modal.attach_file")}</span>
                <button
                  onClick={() => setUploadOpen(false)}
                  className="text-xs text-gray-400 hover:text-gray-600"
                >
                  ✕
                </button>
              </div>
              <FileUpload sessionId={sessionId} onUploaded={handleFileUploaded} />
            </div>
          </div>
        )}

        {/* End chat rating modal */}
        {ratingOpen && (
          <div
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
            onClick={() => !isSubmittingSessionRating && setRatingOpen(false)}
          >
            <form
              onSubmit={handleSessionRatingSubmit}
              className="w-90 rounded-lg border border-gray-200 bg-white p-5 shadow-xl"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="mb-4 flex items-start justify-between gap-4">
                <div>
                  <h2 className="text-sm font-semibold text-gray-800">{t("modal.rate_session")}</h2>
                  <p className="mt-1 text-xs text-gray-500">
                    {t("modal.rate_desc")}
                  </p>
                </div>
                <button
                  type="button"
                  disabled={isSubmittingSessionRating}
                  onClick={() => setRatingOpen(false)}
                  className="text-xs text-gray-400 hover:text-gray-600 disabled:opacity-50"
                >
                  x
                </button>
              </div>

              <div className="grid grid-cols-5 gap-2">
                {SESSION_RATINGS.map((rating) => (
                  <button
                    key={rating}
                    type="button"
                    onClick={() => setSessionRating(rating)}
                    className={`h-10 rounded border text-sm font-semibold transition-colors ${
                      sessionRating === rating
                        ? "border-[#4a6659] bg-[#edf5ef] text-[#1a3a2a]"
                        : "border-gray-200 text-gray-500 hover:border-gray-300"
                    }`}
                  >
                    {rating}
                  </button>
                ))}
              </div>

              <textarea
                value={sessionRatingComment}
                onChange={(e) => setSessionRatingComment(e.target.value)}
                placeholder={t("feedback.optional_comment")}
                rows={3}
                className="mt-3 min-h-24 w-full resize-y rounded border border-gray-200 px-3 py-2 text-sm text-gray-700 outline-none focus:border-[#4a6659] focus:ring-1 focus:ring-[#4a6659]"
              />

              <div className="mt-4 flex justify-end gap-2">
                <button
                  type="button"
                  disabled={isSubmittingSessionRating}
                  onClick={() => setRatingOpen(false)}
                  className="rounded border border-gray-200 px-3 py-2 text-xs font-semibold text-gray-600 hover:bg-gray-50 disabled:opacity-50"
                >
                  {t("btn.cancel")}
                </button>
                <button
                  type="submit"
                  disabled={!sessionRating || isSubmittingSessionRating}
                  className="rounded bg-[#4a6659] px-3 py-2 text-xs font-semibold text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {isSubmittingSessionRating ? t("modal.saving") : t("modal.end_chat")}
                </button>
              </div>
            </form>
          </div>
        )}

        {/* Disclaimer */}
        <div className="shrink-0 px-4 py-1.5 text-center">
          <p className="text-[10px] text-gray-400">
            {t("disclaimer")}
          </p>
        </div>
      </div>

      {/* ── Right panel ────────────────────────────────── */}
      <div className="flex w-1/2 flex-col overflow-hidden">
        <RsDocumentPanel
          activeTab={activeTab}
          onTabChange={setActiveTab}
          rsPartial={rsPartial}
          directFields={directFields}
          onDirectFieldChange={handleDirectFieldChange}
          sessionId={sessionId}
          onGenerateFull={handleGenerateFull}
          srsData={srsData}
          finalizingStatus={finalizingStatus}
          finalAnalysis={finalAnalysis}
          isExtracting={isExtracting}
        />
      </div>
      {error && <ErrorToast message={error} onDismiss={() => setError(null)} />}
    </div>
  );
}
