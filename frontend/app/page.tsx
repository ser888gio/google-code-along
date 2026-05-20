"use client";

import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  streamChat,
  downloadRsTemplateDocx,
  FeedbackVote,
  SessionRating,
  RsPartialData,
  SrsData,
  FinalAnalysis,
  SessionSummary,
  UploadedFile,
} from "../lib/api";
import AnalysisPanel, { FinalizingOverlay } from "./components/AnalysisPanel";
import FileUpload from "./components/FileUpload";
import BpmnPanel from "./components/BpmnPanel";
import DataflowPanel from "./components/DataflowPanel";
import RsLiveTemplate from "./components/RsLiveTemplate";
import FirestoreSrsPanel from "./components/FirestoreSrsPanel";
import LanguageSwitcher from "./i18n/LanguageSwitcher";
import { useLocale } from "./i18n/LocaleContext";
import { DirectChatFieldKey } from "./generated/rsSchema";
import { useMessages, Message } from "./hooks/useMessages";
import { useChatSession, FinalizingStatus } from "./hooks/useChatSession";
import { useRsExtraction } from "./hooks/useRsExtraction";
import {
  useDirectFields,
  DIRECT_INPUT_KEYS,
  SUGGESTABLE_DIRECT_KEYS,
  inferDirectChatFieldFromAssistant,
} from "./hooks/useDirectFields";
import { useVoiceMode, ChatMode } from "./hooks/useVoiceMode";

// ─── Types ────────────────────────────────────────────────────────────────────


const RS_TABS = ["Preview", "BPMN", "Data", "Database", "Analysis", "Summary"] as const;
type RsTab = (typeof RS_TABS)[number];

const SESSION_RATINGS = [1, 2, 3, 4, 5] as const satisfies readonly SessionRating[];

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
  const [localComment, setLocalComment] = useState<string | null>(null);
  const comment = localComment ?? (msg.feedback?.comment ?? "");

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

  async function handleCommentSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!canSendFeedback || !activeVote || feedbackPending) return;
    await onFeedbackComment(msg.id, comment);
    setLocalComment(null);
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
                onChange={(e) => setLocalComment(e.target.value)}
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
      <div className="flex shrink-0 items-center border-b border-gray-200 bg-white px-4">
        <span className="mr-4 border-r border-gray-200 py-3 pr-4 text-sm font-semibold text-gray-800">
          {t("header.rs")}
        </span>
        <div className="flex overflow-x-auto">
          {RS_TABS.map((tab) => {
            // Hide specific tabs
            if (tab === "BPMN" || tab === "Data" || tab === "Analysis") return null;
            return (
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
          )})}
        </div>
      </div>

      <div className="flex-1 overflow-hidden bg-gray-50">
        {activeTab === "Preview" ? (
          <RsLiveTemplate
            rsPartial={rsPartial}
            directFields={directFields}
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
          <div className="flex h-full flex-col items-center justify-center gap-3">
            {(rsPartial?.completeness ?? 0) < 80 && (
              <p className="text-xs text-gray-400">
                {rsPartial?.completeness ?? 0}% — {t("rs.reach_80")} 80%)
              </p>
            )}
            <button
              onClick={onGenerateFull}
              disabled={(rsPartial?.completeness ?? 0) < 80}
              className={`flex items-center gap-2 rounded px-5 py-2.5 text-sm font-semibold transition-opacity ${
                (rsPartial?.completeness ?? 0) >= 80
                  ? "bg-[#4a6659] text-white hover:opacity-90"
                  : "cursor-not-allowed bg-gray-200 text-gray-400"
              }`}
            >
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                <path d="M7 1v8M4 6l3 3 3-3" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
                <path d="M1 10v1a2 2 0 002 2h8a2 2 0 002-2v-1" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
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

// ─── History Sidebar ──────────────────────────────────────────────────────────

function HistorySidebar({
  sessions,
  loading,
  currentSessionId,
  onClose,
  onNewConversation,
  onLoadSession,
}: {
  sessions: SessionSummary[];
  loading: boolean;
  currentSessionId: string | null;
  onClose: () => void;
  onNewConversation: () => void;
  onLoadSession: (id: string) => void;
}) {
  const { t } = useLocale();
  return (
    <div className="absolute inset-0 z-40 flex">
      <div className="flex w-72 flex-col border-r border-gray-200 bg-white shadow-xl">
        <div className="flex shrink-0 items-center justify-between border-b border-gray-200 px-4 py-3">
          <span className="text-sm font-bold text-gray-800">{t("sidebar.conversations")}</span>
          <button onClick={onClose} className="text-xs text-gray-400 hover:text-gray-600">✕</button>
        </div>
        <div className="shrink-0 border-b border-gray-200 p-3">
          <button
            onClick={onNewConversation}
            className="w-full rounded border border-dashed border-gray-300 py-2 text-xs font-semibold text-gray-500 hover:border-[#4caf50] hover:text-[#4a6659] transition-colors"
          >
            {t("btn.new_conversation")}
          </button>
        </div>
        <div className="flex-1 overflow-y-auto">
          {loading ? (
            <p className="p-4 text-center text-xs text-gray-400">{t("sidebar.loading")}</p>
          ) : sessions.length === 0 ? (
            <p className="p-4 text-center text-xs text-gray-400">{t("sidebar.no_conversations")}</p>
          ) : (
            sessions.map((s) => (
              <button
                key={s.session_id}
                onClick={() => onLoadSession(s.session_id)}
                className={`w-full border-b border-gray-100 px-4 py-3 text-left hover:bg-gray-50 transition-colors ${s.session_id === currentSessionId ? "bg-[#f5fdf5]" : ""}`}
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
      <div className="flex-1 bg-black/20" onClick={onClose} />
    </div>
  );
}

// ─── Chat Header ──────────────────────────────────────────────────────────────

function ChatHeader({
  activeWorkflowField,
  chatMode,
  isStreaming,
  wsConnectionState,
  isRecording,
  onOpenHistory,
  onToggleVoice,
}: {
  activeWorkflowField: string | null;
  chatMode: ChatMode;
  isStreaming: boolean;
  wsConnectionState: string;
  isRecording: boolean;
  onOpenHistory: () => void;
  onToggleVoice: () => void;
}) {
  const { t } = useLocale();
  return (
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
        <button
          onClick={onOpenHistory}
          className="flex items-center gap-1.5 rounded px-2 py-1 text-xs text-gray-500 hover:bg-gray-100"
        >
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
            <circle cx="7" cy="7" r="6" stroke="currentColor" strokeWidth="1.5" />
            <path d="M7 4v3.5l2 2" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          {t("btn.history")}
        </button>
        <button
          onClick={onToggleVoice}
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
        <LanguageSwitcher />
        <div className={`h-3 w-3 rounded-full ${
          chatMode === "voice"
            ? wsConnectionState === "connected"
              ? isRecording
                ? "animate-pulse bg-red-500"
                : "bg-blue-500"
              : wsConnectionState === "connecting"
                ? "animate-pulse bg-yellow-400"
                : "bg-gray-400"
            : isStreaming
              ? "animate-pulse bg-yellow-400"
              : "bg-[#4caf50]"
        }`} />
      </div>
    </div>
  );
}

// ─── Chat Input Area ──────────────────────────────────────────────────────────

function ChatInput({
  chatMode,
  input,
  isStreaming,
  sessionEnded,
  sessionId,
  wsConnectionState,
  isRecording,
  isPlaying,
  recorderError,
  textareaRef,
  onInputChange,
  onKeyDown,
  onSend,
  onOpenUpload,
  onOpenRating,
  onMicToggle,
}: {
  chatMode: ChatMode;
  input: string;
  isStreaming: boolean;
  sessionEnded: boolean;
  sessionId: string | null;
  wsConnectionState: string;
  isRecording: boolean;
  isPlaying: boolean;
  recorderError: string | null;
  textareaRef: React.RefObject<HTMLTextAreaElement | null>;
  onInputChange: (value: string) => void;
  onKeyDown: (e: React.KeyboardEvent<HTMLTextAreaElement>) => void;
  onSend: () => void;
  onOpenUpload: () => void;
  onOpenRating: () => void;
  onMicToggle: () => void;
}) {
  const { t } = useLocale();
  const isVoiceConnected = wsConnectionState === "connected";

  return (
    <div className="shrink-0 border-t border-gray-200 p-3">
      {chatMode === "voice" ? (
        <div className="flex flex-col items-center gap-2">
          {wsConnectionState === "connecting" && (
            <p className="text-xs text-yellow-600">{t("voice.connecting")}</p>
          )}
          {wsConnectionState === "error" && (
            <p className="text-xs text-red-600">{t("voice.conn_failed")}</p>
          )}
          {recorderError && (
            <p className="text-xs text-red-600">{recorderError}</p>
          )}
          <div className="flex items-center gap-3">
            <button
              onClick={onMicToggle}
              disabled={!isVoiceConnected || sessionEnded}
              title={isRecording ? "Stop speaking" : "Start speaking"}
              className={`flex h-12 w-12 items-center justify-center rounded-full transition-all ${
                isRecording
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
              {isRecording
                ? t("voice.listening")
                : isPlaying
                  ? t("voice.ai_speaking")
                  : isVoiceConnected
                    ? sessionEnded ? t("voice.chat_ended") : t("voice.tap_to_speak")
                    : t("voice.connecting")}
            </span>
          </div>
        </div>
      ) : (
        <div className="flex items-end gap-2">
          <button
            onClick={onOpenUpload}
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
            onChange={(e) => onInputChange(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder={t("input.placeholder")}
            rows={1}
            disabled={isStreaming || sessionEnded}
            className="flex-1 resize-none rounded border border-gray-200 bg-white px-3 py-2 text-sm text-gray-800 placeholder-gray-400 outline-none focus:border-[#4caf50] disabled:opacity-50"
            style={{ minHeight: 40, maxHeight: 160 }}
          />
          <div className="flex shrink-0 flex-col gap-2">
            <button
              onClick={onSend}
              disabled={!input.trim() || isStreaming || sessionEnded}
              className="flex items-center gap-1.5 rounded bg-[#4a6659] px-4 py-2.5 text-sm font-semibold text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
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
            <button
              onClick={onOpenRating}
              disabled={!sessionId || isStreaming || sessionEnded}
              className="flex items-center justify-center gap-1.5 rounded border border-gray-200 px-2 py-2 text-xs font-semibold text-gray-600 transition-colors hover:border-[#4a6659] hover:text-[#1a3a2a] disabled:cursor-not-allowed disabled:opacity-40"
            >
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                <path d="M3 3l8 8M11 3l-8 8" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
              </svg>
              {sessionEnded ? t("btn.ended") : t("btn.end_chat")}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Session Rating Modal ─────────────────────────────────────────────────────

function SessionRatingModal({
  open,
  rating,
  comment,
  submitting,
  onClose,
  onRatingChange,
  onCommentChange,
  onSubmit,
}: {
  open: boolean;
  rating: SessionRating | null;
  comment: string;
  submitting: boolean;
  onClose: () => void;
  onRatingChange: (rating: SessionRating) => void;
  onCommentChange: (comment: string) => void;
  onSubmit: (e: React.FormEvent<HTMLFormElement>) => void;
}) {
  const { t } = useLocale();
  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      onClick={() => !submitting && onClose()}
    >
      <form
        onSubmit={onSubmit}
        className="w-90 rounded-lg border border-gray-200 bg-white p-5 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-start justify-between gap-4">
          <div>
            <h2 className="text-sm font-semibold text-gray-800">{t("modal.rate_session")}</h2>
            <p className="mt-1 text-xs text-gray-500">{t("modal.rate_desc")}</p>
          </div>
          <button
            type="button"
            disabled={submitting}
            onClick={onClose}
            className="text-xs text-gray-400 hover:text-gray-600 disabled:opacity-50"
          >
            x
          </button>
        </div>
        <div className="grid grid-cols-5 gap-2">
          {SESSION_RATINGS.map((option) => (
            <button
              key={option}
              type="button"
              onClick={() => onRatingChange(option)}
              className={`h-10 rounded border text-sm font-semibold transition-colors ${
                rating === option
                  ? "border-[#4a6659] bg-[#edf5ef] text-[#1a3a2a]"
                  : "border-gray-200 text-gray-500 hover:border-gray-300"
              }`}
            >
              {option}
            </button>
          ))}
        </div>
        <textarea
          value={comment}
          onChange={(e) => onCommentChange(e.target.value)}
          placeholder={t("feedback.optional_comment")}
          rows={3}
          className="mt-3 min-h-24 w-full resize-y rounded border border-gray-200 px-3 py-2 text-sm text-gray-700 outline-none focus:border-[#4a6659] focus:ring-1 focus:ring-[#4a6659]"
        />
        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            disabled={submitting}
            onClick={onClose}
            className="rounded border border-gray-200 px-3 py-2 text-xs font-semibold text-gray-600 hover:bg-gray-50 disabled:opacity-50"
          >
            {t("btn.cancel")}
          </button>
          <button
            type="submit"
            disabled={!rating || submitting}
            className="rounded bg-[#4a6659] px-3 py-2 text-xs font-semibold text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {submitting ? t("modal.saving") : t("modal.end_chat")}
          </button>
        </div>
      </form>
    </div>
  );
}

// ─── Chat Transcript ──────────────────────────────────────────────────────────

function ChatTranscript({
  messages,
  sessionId,
  bottomRef,
  onFeedback,
  onFeedbackComment,
}: {
  messages: Message[];
  sessionId: string | null;
  bottomRef: React.RefObject<HTMLDivElement | null>;
  onFeedback: (localId: string, vote: FeedbackVote) => Promise<void>;
  onFeedbackComment: (localId: string, comment: string) => Promise<void>;
}) {
  return (
    <div className="flex-1 space-y-3 overflow-y-auto px-4 py-3">
      {messages.map((msg) => (
        <MessageBubble
          key={msg.id}
          msg={msg}
          sessionId={sessionId}
          onFeedback={onFeedback}
          onFeedbackComment={onFeedbackComment}
        />
      ))}
      <div ref={bottomRef} />
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function ChatPage() {
  const { locale, t } = useLocale();
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<RsTab>("Preview");
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [activeWorkflowField, setActiveWorkflowField] = useState<string | null>(null);

  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const pendingDirectChatFieldRef = useRef<DirectChatFieldKey | null>(null);

  const msgs = useMessages(t("welcome_message"));
  const session = useChatSession(setError);
  const rs = useRsExtraction();
  const fields = useDirectFields(rs.setRsPartial);
  const voice = useVoiceMode({
    addMessage: msgs.addMessage,
    appendToMessage: msgs.appendToMessage,
    replaceMessageText: msgs.replaceMessageText,
    finalizeMessage: msgs.finalizeMessage,
    setRsPartial: rs.setRsPartial,
    setDirectFields: fields.setDirectFields,
    setSrsData: rs.setSrsData,
    setFinalizingStatus: rs.setFinalizingStatus,
    setActiveTab: (tab) => setActiveTab(tab as RsTab),
    setIsExtracting: rs.setIsExtracting,
    extractNonceRef: rs.extractNonceRef,
    setError,
    sessionId: session.sessionId,
    directFields: fields.directFields,
  });

  // Re-initialize welcome message when locale changes
  useEffect(() => {
    msgs.resetMessages(t("welcome_message"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [locale]);

  // Scroll to bottom on new messages
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [msgs.messages]);

  // Auto-resize textarea
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, [input]);

  // Refresh uploads when session is established
  useEffect(() => {
    if (!session.sessionId) return;
    fields.refreshSessionUploads(session.sessionId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session.sessionId]);

  // Start analysis polling when finalizing
  useEffect(() => {
    if (rs.finalizingStatus !== "finalizing" || !session.sessionId) return;
    return rs.startPolling(session.sessionId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rs.finalizingStatus, session.sessionId]);

  async function handleSend() {
    const text = input.trim();
    if (!text || isStreaming || session.sessionEnded) return;

    setInput("");
    setError(null);
    const { directFieldsForRequest, deferredFieldsForRequest } = fields.applyDirectChatAnswer(
      text,
      pendingDirectChatFieldRef,
      session.sessionId
    );

    msgs.addMessage("user", text);
    setIsStreaming(true);
    const assistantId = msgs.addMessage("assistant", "", true);
    let assistantText = "";
    let capturedSessionId = session.sessionId;

    await streamChat(
      text,
      session.sessionId,
      (chunk) => {
        assistantText += chunk;
        msgs.appendToMessage(assistantId, chunk);
      },
      (id) => {
        capturedSessionId = id;
        session.setSessionId(id);
      },
      async () => {
        msgs.finalizeMessage(assistantId);
        setIsStreaming(false);
        pendingDirectChatFieldRef.current = inferDirectChatFieldFromAssistant(assistantText);

        if (capturedSessionId) {
          rs.setIsExtracting(true);
          const nonce = rs.beginExtraction();
          await rs.runPostTurnExtraction(capturedSessionId, directFieldsForRequest, nonce, fields.setDirectFields);
        } else {
          rs.setIsExtracting(false);
        }
      },
      (err) => {
        msgs.finalizeMessage(assistantId);
        setError(err);
        setIsStreaming(false);
        rs.setIsExtracting(false);
      },
      () => {
        rs.setFinalizingStatus("finalizing");
        setActiveTab("Analysis");
      },
      (key, value) => {
        if (DIRECT_INPUT_KEYS.has(key)) return;
        rs.setRsPartial((prev) => ({
          completeness: prev?.completeness ?? 0,
          fields: { ...(prev?.fields ?? {}), [key]: { filled: true, value } },
        }));
        if (SUGGESTABLE_DIRECT_KEYS.has(key) && !(directFieldsForRequest[key] ?? "").trim()) {
          fields.setDirectFields((prev) => ({ ...prev, [key]: value }));
          fields.setDeferredDirectFields((prev) => prev.filter((f) => f !== key));
        }
      },
      directFieldsForRequest,
      deferredFieldsForRequest,
      (key) => setActiveWorkflowField(key),
      (messageId) => msgs.setMessageBackendId(assistantId, messageId),
    );
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void handleSend();
    }
  }

  async function handleGenerateFull() {
    if (!session.sessionId) return;
    try {
      await downloadRsTemplateDocx(session.sessionId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to generate document");
    }
  }

  async function handleLoadSession(sid: string) {
    const loaded = await session.loadSession(sid);
    msgs.loadMessages(loaded.messages);
    rs.setRsPartial(loaded.rsPartial);
    fields.setDirectFields(loaded.directFields);
    rs.setSrsData(loaded.srsData);
    rs.setFinalAnalysis(loaded.finalAnalysis);
    rs.setFinalizingStatus(loaded.finalizingStatus);
    fields.setDeferredDirectFields([]);
    setActiveWorkflowField(null);
    if (loaded.finalizingStatus === "complete") setActiveTab("Analysis");
  }

  function newConversation() {
    msgs.resetMessages(t("welcome_message"));
    session.resetSession(t("welcome_message"));
    rs.resetExtraction();
    fields.resetDirectFields();
    setActiveWorkflowField(null);
    if (voice.chatMode === "voice") voice.stopVoice();
  }

  function openSessionRating() {
    if (!session.sessionId || isStreaming) return;
    if (voice.chatMode === "voice") voice.stopVoice();
    session.setRatingOpen(true);
  }

  async function handleFileUploaded(file: UploadedFile) {
    const sid = file.sessionId ?? session.sessionId;
    if (sid) {
      if (!session.sessionId) session.setSessionId(sid);
      await fields.refreshSessionUploads(sid, [file]);
    }
    setUploadOpen(false);
  }

  return (
    <div className="flex h-screen overflow-hidden bg-gray-100 font-sans">
      {/* ── Left panel ─────────────────────────────────── */}
      <div className="flex w-1/2 shrink-0 flex-col border-r border-gray-200 bg-white">
        {session.historyOpen && (
          <HistorySidebar
            sessions={session.historySessions}
            loading={session.historyLoading}
            currentSessionId={session.sessionId}
            onClose={() => session.setHistoryOpen(false)}
            onNewConversation={newConversation}
            onLoadSession={handleLoadSession}
          />
        )}

        <ChatHeader
          activeWorkflowField={activeWorkflowField}
          chatMode={voice.chatMode}
          isStreaming={isStreaming}
          wsConnectionState={voice.ws.connectionState}
          isRecording={voice.audioRecorder.isRecording}
          onOpenHistory={session.openHistory}
          onToggleVoice={() => voice.handleToggleVoice(session.sessionId, session.setSessionId)}
        />

        <ChatTranscript
          messages={msgs.messages}
          sessionId={session.sessionId}
          bottomRef={bottomRef}
          onFeedback={(id, vote) => msgs.handleFeedback(id, vote, session.sessionId, setError)}
          onFeedbackComment={(id, comment) =>
            msgs.handleFeedbackComment(id, comment, session.sessionId, setError)
          }
        />

        <ChatInput
          chatMode={voice.chatMode}
          input={input}
          isStreaming={isStreaming}
          sessionEnded={session.sessionEnded}
          sessionId={session.sessionId}
          wsConnectionState={voice.ws.connectionState}
          isRecording={voice.audioRecorder.isRecording}
          isPlaying={voice.audioPlayer.isPlaying}
          recorderError={voice.audioRecorder.error}
          textareaRef={textareaRef}
          onInputChange={setInput}
          onKeyDown={handleKeyDown}
          onSend={() => void handleSend()}
          onOpenUpload={() => setUploadOpen(true)}
          onOpenRating={openSessionRating}
          onMicToggle={() => void voice.handleMicToggle()}
        />

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
              <FileUpload
                sessionId={session.sessionId}
                onUploaded={handleFileUploaded}
                onEnsureSession={session.ensureSession}
              />
            </div>
          </div>
        )}

        <SessionRatingModal
          open={session.ratingOpen}
          rating={session.sessionRating}
          comment={session.sessionRatingComment}
          submitting={session.isSubmittingSessionRating}
          onClose={() => session.setRatingOpen(false)}
          onRatingChange={session.setSessionRating}
          onCommentChange={session.setSessionRatingComment}
          onSubmit={session.handleSessionRatingSubmit}
        />

        <div className="shrink-0 px-4 py-1.5 text-center">
          <p className="text-[10px] text-gray-400">{t("disclaimer")}</p>
        </div>
      </div>

      {/* ── Right panel ────────────────────────────────── */}
      <div className="flex w-1/2 flex-col overflow-hidden">
        <RsDocumentPanel
          activeTab={activeTab}
          onTabChange={setActiveTab}
          rsPartial={rs.rsPartial}
          directFields={fields.directFields}
          onDirectFieldChange={(key, value) =>
            fields.handleDirectFieldChange(key, value, session.sessionId)
          }
          sessionId={session.sessionId}
          onGenerateFull={handleGenerateFull}
          srsData={rs.srsData}
          finalizingStatus={rs.finalizingStatus}
          finalAnalysis={rs.finalAnalysis}
          isExtracting={rs.isExtracting}
        />
      </div>

      {error && <ErrorToast message={error} onDismiss={() => setError(null)} />}
    </div>
  );
}
