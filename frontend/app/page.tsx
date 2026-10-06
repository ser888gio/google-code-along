"use client";

import { type ReactNode, useEffect, useRef, useState } from "react";
import {
	type FinalAnalysis,
	type RsState,
	type SessionRating,
	type SessionSummary,
	type SrsData,
	type UploadedFile,
	downloadRsTemplateDocx,
	streamChat,
} from "../lib/api";
import AnalysisPanel, { FinalizingOverlay } from "./components/AnalysisPanel";
import BpmnPanel from "./components/BpmnPanel";
import ChatTranscript from "./components/ChatTranscript";
import DataflowPanel from "./components/DataflowPanel";
import ErrorToast from "./components/ErrorToast";
import FileUpload from "./components/FileUpload";
import FirestoreSrsPanel from "./components/FirestoreSrsPanel";
import RsLiveTemplate from "./components/RsLiveTemplate";
import { type FinalizingStatus, useChatSession } from "./hooks/useChatSession";
import { useMessages } from "./hooks/useMessages";
import { useRsExtraction } from "./hooks/useRsExtraction";
import { useRsState } from "./hooks/useRsState";
import { type ChatMode, useVoiceMode } from "./hooks/useVoiceMode";
import LanguageSwitcher from "./i18n/LanguageSwitcher";
import { useLocale } from "./i18n/LocaleContext";
import {
	type DirectChatFieldKey,
	inferDirectChatFieldFromAssistant,
} from "./lib/directChatAnswer";

// ─── Types ────────────────────────────────────────────────────────────────────

const RS_TABS = [
	"Preview",
	"BPMN",
	"Data",
	"Database",
	"Analysis",
	"Summary",
] as const;
type RsTab = (typeof RS_TABS)[number];
// BPMN, Data and Analysis are hidden from the tab bar; Analysis is still opened programmatically on finalization.
const HIDDEN_TABS = new Set<RsTab>(["BPMN", "Data", "Analysis"]);

const SESSION_RATINGS = [
	1, 2, 3, 4, 5,
] as const satisfies readonly SessionRating[];

// ─── RS Document Panel ────────────────────────────────────────────────────────

function RsDocumentPanel({
	activeTab,
	onTabChange,
	rsState,
	rsCompleteness,
	onFieldChange,
	onAcceptSuggestion,
	onDismissSuggestion,
	sessionId,
	onGenerateFull,
	isDownloadingRs,
	srsData,
	finalizingStatus,
	finalAnalysis,
	isExtracting,
	recentlyChangedKeys,
	clearChangedKey,
	clearAllChangedKeys,
}: {
	activeTab: RsTab;
	onTabChange: (t: RsTab) => void;
	rsState: RsState;
	rsCompleteness: number;
	onFieldChange: (key: string, value: string) => void;
	onAcceptSuggestion: (key: string) => void;
	onDismissSuggestion: (key: string) => void;
	sessionId: string | null;
	onGenerateFull: () => void;
	isDownloadingRs: boolean;
	srsData: SrsData | null;
	finalizingStatus: FinalizingStatus;
	finalAnalysis: FinalAnalysis | null;
	isExtracting: boolean;
	recentlyChangedKeys: Set<string>;
	clearChangedKey: (key: string) => void;
	clearAllChangedKeys: () => void;
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

	const panels: Partial<Record<RsTab, ReactNode>> = {
		Preview: (
			<RsLiveTemplate
				state={rsState}
				completeness={rsCompleteness}
				onFieldChange={onFieldChange}
				onAcceptSuggestion={onAcceptSuggestion}
				onDismissSuggestion={onDismissSuggestion}
				isExtracting={isExtracting}
				recentlyChangedKeys={recentlyChangedKeys}
				clearChangedKey={clearChangedKey}
				clearAllChangedKeys={clearAllChangedKeys}
			/>
		),
		BPMN: <BpmnPanel sessionId={sessionId} />,
		Data: <DataflowPanel sessionId={sessionId} />,
		Database: <FirestoreSrsPanel data={srsData} />,
		Analysis: (
			<AnalysisTabContent
				finalizingStatus={finalizingStatus}
				finalAnalysis={finalAnalysis}
			/>
		),
		Summary: (
			<SummaryTabContent
				rsCompleteness={rsCompleteness}
				isDownloadingRs={isDownloadingRs}
				onGenerateFull={onGenerateFull}
			/>
		),
	};

	return (
		<div className="flex h-full flex-col">
			<div className="flex shrink-0 items-center border-b border-gray-200 bg-white px-4">
				<span className="mr-4 border-r border-gray-200 py-3 pr-4 text-sm font-semibold text-gray-800">
					{t("header.rs")}
				</span>
				<div className="flex overflow-x-auto">
					{RS_TABS.filter((tab) => !HIDDEN_TABS.has(tab)).map((tab) => (
						<button
							type="button"
							key={tab}
							onClick={() => onTabChange(tab)}
							className={`relative whitespace-nowrap px-3 py-3 text-sm transition-colors ${
								activeTab === tab
									? "border-b-2 border-[#1a3a2a] bg-[#1a3a2a] text-white"
									: "text-gray-500 hover:text-gray-800"
							}`}
						>
							{TAB_LABELS[tab] ?? tab}
						</button>
					))}
				</div>
			</div>

			<div className="flex-1 overflow-hidden bg-gray-50">
				{panels[activeTab] ?? (
					<div className="flex h-full items-center justify-center text-sm text-gray-400">
						{TAB_LABELS[activeTab] ?? activeTab}
					</div>
				)}
			</div>
		</div>
	);
}

function AnalysisTabContent({
	finalizingStatus,
	finalAnalysis,
}: {
	finalizingStatus: FinalizingStatus;
	finalAnalysis: FinalAnalysis | null;
}) {
	const { t } = useLocale();
	if (finalizingStatus === "complete" && finalAnalysis)
		return <AnalysisPanel analysis={finalAnalysis} />;
	if (finalizingStatus === "finalizing") return <FinalizingOverlay />;
	return (
		<div className="flex h-full items-center justify-center text-sm text-gray-400">
			{t("analysis.pending")}
		</div>
	);
}

function SummaryTabContent({
	rsCompleteness,
	isDownloadingRs,
	onGenerateFull,
}: {
	rsCompleteness: number;
	isDownloadingRs: boolean;
	onGenerateFull: () => void;
}) {
	const { t } = useLocale();
	return (
		<div className="flex h-full flex-col items-center justify-center gap-3">
			{rsCompleteness < 80 && (
				<p className="text-xs text-gray-400">
					{rsCompleteness}% — {t("rs.reach_80")} 80%)
				</p>
			)}
			<button
				type="button"
				onClick={onGenerateFull}
				disabled={rsCompleteness < 80 || isDownloadingRs}
				className={`flex items-center gap-2 rounded px-5 py-2.5 text-sm font-semibold transition-opacity ${
					rsCompleteness >= 80 && !isDownloadingRs
						? "bg-[#4a6659] text-white hover:opacity-90"
						: "cursor-not-allowed bg-gray-200 text-gray-400"
				}`}
			>
				{isDownloadingRs ? (
					<svg
						aria-hidden="true"
						width="14"
						height="14"
						viewBox="0 0 14 14"
						fill="none"
						className="animate-spin"
					>
						<circle
							cx="7"
							cy="7"
							r="6"
							stroke="currentColor"
							strokeWidth="1.8"
							strokeDasharray="28"
							strokeDashoffset="10"
							strokeLinecap="round"
						/>
					</svg>
				) : (
					<svg
						aria-hidden="true"
						width="14"
						height="14"
						viewBox="0 0 14 14"
						fill="none"
					>
						<path
							d="M7 1v8M4 6l3 3 3-3"
							stroke="currentColor"
							strokeWidth="1.8"
							strokeLinecap="round"
							strokeLinejoin="round"
						/>
						<path
							d="M1 10v1a2 2 0 002 2h8a2 2 0 002-2v-1"
							stroke="currentColor"
							strokeWidth="1.8"
							strokeLinecap="round"
						/>
					</svg>
				)}
				{isDownloadingRs ? t("download.generating") : t("download.rs")}
			</button>
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
					<span className="text-sm font-bold text-gray-800">
						{t("sidebar.conversations")}
					</span>
					<button
						type="button"
						onClick={onClose}
						className="text-xs text-gray-400 hover:text-gray-600"
					>
						✕
					</button>
				</div>
				<div className="shrink-0 border-b border-gray-200 p-3">
					<button
						type="button"
						onClick={onNewConversation}
						className="w-full rounded border border-dashed border-gray-300 py-2 text-xs font-semibold text-gray-500 hover:border-[#4caf50] hover:text-[#4a6659] transition-colors"
					>
						{t("btn.new_conversation")}
					</button>
				</div>
				<div className="flex-1 overflow-y-auto">
					{loading ? (
						<p className="p-4 text-center text-xs text-gray-400">
							{t("sidebar.loading")}
						</p>
					) : sessions.length === 0 ? (
						<p className="p-4 text-center text-xs text-gray-400">
							{t("sidebar.no_conversations")}
						</p>
					) : (
						sessions.map((s) => (
							<button
								type="button"
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
			<div
				className="flex-1 bg-black/20"
				role="button"
				tabIndex={0}
				aria-label="Close"
				onClick={onClose}
				onKeyDown={(e) =>
					e.key === "Enter" || e.key === " " ? onClose() : undefined
				}
			/>
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
		<div className="flex shrink-0 items-center justify-between border-b border-gray-200 px-4 py-2">
			<div className="flex items-center gap-2">
				<span className="text-sm font-bold text-gray-800">
					{t("header.title")}
				</span>
				{activeWorkflowField && (
					<span className="rounded border border-gray-200 bg-gray-50 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-gray-500">
						{activeWorkflowField.replace(/_/g, " ")}
					</span>
				)}
			</div>
			<div className="flex items-center gap-3">
				<button
					type="button"
					onClick={onOpenHistory}
					className="flex items-center gap-1.5 rounded px-2 py-1 text-xs text-gray-500 hover:bg-gray-100"
				>
					<svg
						aria-hidden="true"
						width="14"
						height="14"
						viewBox="0 0 14 14"
						fill="none"
					>
						<circle
							cx="7"
							cy="7"
							r="6"
							stroke="currentColor"
							strokeWidth="1.5"
						/>
						<path
							d="M7 4v3.5l2 2"
							stroke="currentColor"
							strokeWidth="1.5"
							strokeLinecap="round"
							strokeLinejoin="round"
						/>
					</svg>
					{t("btn.history")}
				</button>
				<button
					type="button"
					onClick={onToggleVoice}
					disabled={chatMode === "text" && isStreaming}
					title={
						chatMode === "voice"
							? t("header.voice_to_text")
							: t("header.text_to_voice")
					}
					className={`flex items-center gap-1.5 rounded px-2 py-1 text-xs transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
						chatMode === "voice"
							? "bg-red-50 text-red-600 hover:bg-red-100"
							: "text-gray-500 hover:bg-gray-100"
					}`}
				>
					{chatMode === "voice" ? (
						<>
							<svg
								aria-hidden="true"
								width="14"
								height="14"
								viewBox="0 0 24 24"
								fill="none"
							>
								<path
									d="M12 1a3 3 0 00-3 3v8a3 3 0 006 0V4a3 3 0 00-3-3z"
									fill="currentColor"
								/>
								<path
									d="M19 10v2a7 7 0 01-14 0v-2"
									stroke="currentColor"
									strokeWidth="2"
									strokeLinecap="round"
								/>
								<path
									d="M12 19v4M8 23h8"
									stroke="currentColor"
									strokeWidth="2"
									strokeLinecap="round"
								/>
							</svg>
							{t("btn.voice_mode")}
						</>
					) : (
						<>
							<svg
								aria-hidden="true"
								width="14"
								height="14"
								viewBox="0 0 24 24"
								fill="none"
							>
								<path
									d="M12 1a3 3 0 00-3 3v8a3 3 0 006 0V4a3 3 0 00-3-3z"
									stroke="currentColor"
									strokeWidth="2"
								/>
								<path
									d="M19 10v2a7 7 0 01-14 0v-2"
									stroke="currentColor"
									strokeWidth="2"
									strokeLinecap="round"
								/>
								<path
									d="M12 19v4M8 23h8"
									stroke="currentColor"
									strokeWidth="2"
									strokeLinecap="round"
								/>
							</svg>
							{t("btn.voice")}
						</>
					)}
				</button>
				<div
					className={`h-3 w-3 rounded-full ${
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
					}`}
				/>
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
							type="button"
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
							<svg
								aria-hidden="true"
								width="20"
								height="20"
								viewBox="0 0 24 24"
								fill="none"
							>
								<path
									d="M12 1a3 3 0 00-3 3v8a3 3 0 006 0V4a3 3 0 00-3-3z"
									fill="currentColor"
								/>
								<path
									d="M19 10v2a7 7 0 01-14 0v-2"
									stroke="currentColor"
									strokeWidth="2"
									strokeLinecap="round"
								/>
								<path
									d="M12 19v4M8 23h8"
									stroke="currentColor"
									strokeWidth="2"
									strokeLinecap="round"
								/>
							</svg>
						</button>
						<span className="text-xs text-gray-500">
							{isRecording
								? t("voice.listening")
								: isPlaying
									? t("voice.ai_speaking")
									: isVoiceConnected
										? sessionEnded
											? t("voice.chat_ended")
											: t("voice.tap_to_speak")
										: t("voice.connecting")}
						</span>
					</div>
				</div>
			) : (
				<div className="flex items-end gap-2">
					<button
						type="button"
						onClick={onOpenUpload}
						title="Attach a file"
						disabled={sessionEnded}
						className="flex shrink-0 items-center justify-center rounded border border-gray-200 bg-white text-gray-500 hover:border-[#4caf50] hover:text-[#4caf50] transition-colors"
						style={{ width: 40, height: 40 }}
					>
						<svg
							aria-hidden="true"
							width="18"
							height="18"
							viewBox="0 0 18 18"
							fill="none"
						>
							<path
								d="M9 4v10M4 9h10"
								stroke="currentColor"
								strokeWidth="1.8"
								strokeLinecap="round"
							/>
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
						className="flex-1 resize-none rounded border border-gray-200 bg-white px-3 py-2 text-base text-gray-800 placeholder-gray-400 outline-none focus:border-[#4caf50] disabled:opacity-50"
						style={{ minHeight: 40, maxHeight: 160 }}
					/>
					<div className="flex shrink-0 flex-col gap-2">
						<button
							type="button"
							onClick={onSend}
							disabled={!input.trim() || isStreaming || sessionEnded}
							className="flex items-center gap-1.5 rounded bg-[#4a6659] px-4 py-2.5 text-base font-semibold text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
						>
							{isStreaming ? (
								<svg
									aria-hidden="true"
									className="animate-spin"
									width="16"
									height="16"
									viewBox="0 0 24 24"
									fill="none"
								>
									<circle
										cx="12"
										cy="12"
										r="10"
										stroke="white"
										strokeWidth="3"
										strokeDasharray="31.4"
										strokeDashoffset="10"
									/>
								</svg>
							) : (
								<>
									{t("btn.send")}
									<svg
										aria-hidden="true"
										width="14"
										height="14"
										viewBox="0 0 14 14"
										fill="none"
									>
										<path
											d="M2 7h10M7 2l5 5-5 5"
											stroke="white"
											strokeWidth="1.8"
											strokeLinecap="round"
											strokeLinejoin="round"
										/>
									</svg>
								</>
							)}
						</button>
						<button
							type="button"
							onClick={onOpenRating}
							disabled={!sessionId || isStreaming || sessionEnded}
							className="flex items-center justify-center gap-1.5 rounded border border-gray-200 px-2 py-2 text-xs font-semibold text-gray-600 transition-colors hover:border-[#4a6659] hover:text-[#1a3a2a] disabled:cursor-not-allowed disabled:opacity-40"
						>
							<svg
								aria-hidden="true"
								width="14"
								height="14"
								viewBox="0 0 14 14"
								fill="none"
							>
								<path
									d="M3 3l8 8M11 3l-8 8"
									stroke="currentColor"
									strokeWidth="1.7"
									strokeLinecap="round"
								/>
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
			role="button"
			tabIndex={0}
			aria-label="Close"
			onClick={() => !submitting && onClose()}
			onKeyDown={(e) => {
				if ((e.key === "Enter" || e.key === " ") && !submitting) onClose();
			}}
		>
			<form
				onSubmit={onSubmit}
				className="w-90 rounded-lg border border-gray-200 bg-white p-5 shadow-xl"
				onClick={(e) => e.stopPropagation()}
				onKeyDown={(e) => e.stopPropagation()}
			>
				<div className="mb-4 flex items-start justify-between gap-4">
					<div>
						<h2 className="text-sm font-semibold text-gray-800">
							{t("modal.rate_session")}
						</h2>
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

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function ChatPage() {
	const { locale, t } = useLocale();
	const [error, setError] = useState<string | null>(null);
	const [isDownloadingRs, setIsDownloadingRs] = useState(false);
	const [activeTab, setActiveTab] = useState<RsTab>("Preview");
	const [input, setInput] = useState("");
	const [isStreaming, setIsStreaming] = useState(false);
	const [uploadOpen, setUploadOpen] = useState(false);
	const [activeWorkflowField, setActiveWorkflowField] = useState<string | null>(
		null,
	);

	const bottomRef = useRef<HTMLDivElement>(null);
	const textareaRef = useRef<HTMLTextAreaElement>(null);
	const pendingDirectChatFieldRef = useRef<DirectChatFieldKey | null>(null);

	const msgs = useMessages(t("welcome_message"));
	const session = useChatSession(setError);
	const rsState = useRsState(session.sessionId);
	const rs = useRsExtraction(rsState.applyExtraction);
	const voice = useVoiceMode({
		addMessage: msgs.addMessage,
		appendToMessage: msgs.appendToMessage,
		replaceMessageText: msgs.replaceMessageText,
		finalizeMessage: msgs.finalizeMessage,
		applyExtraction: rsState.applyExtraction,
		setSrsData: rs.setSrsData,
		setFinalizingStatus: rs.setFinalizingStatus,
		setActiveTab: (tab) => setActiveTab(tab as RsTab),
		setIsExtracting: rs.setIsExtracting,
		extractNonceRef: rs.extractNonceRef,
		setError,
		sessionId: session.sessionId,
	});

	// Translate the synthetic welcome bubble without clearing real transcripts.
	// biome-ignore lint/correctness/useExhaustiveDependencies: intentional — only re-run when locale changes
	useEffect(() => {
		msgs.updateWelcomeMessage(t("welcome_message"));
	}, [locale]);

	// Scroll to bottom on new messages
	// biome-ignore lint/correctness/useExhaustiveDependencies: intentional — trigger on message list changes
	useEffect(() => {
		bottomRef.current?.scrollIntoView({ behavior: "smooth" });
	}, [msgs.messages]);

	// Auto-resize textarea
	// biome-ignore lint/correctness/useExhaustiveDependencies: intentional — trigger on input changes
	useEffect(() => {
		const el = textareaRef.current;
		if (!el) return;
		el.style.height = "auto";
		el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
	}, [input]);

	// (Upload state is restored via hydrateFromSession when loading a saved session)

	// Start analysis polling when finalizing
	// biome-ignore lint/correctness/useExhaustiveDependencies: intentional — startPolling is stable
	useEffect(() => {
		if (rs.finalizingStatus !== "finalizing" || !session.sessionId) return;
		return rs.startPolling(session.sessionId);
	}, [rs.finalizingStatus, session.sessionId]);

	function handleChoiceSelect(msgId: string, choice: string) {
		msgs.clearMessageChoices(msgId);
		if (choice) void handleSend(choice);
	}

	async function handleSend(overrideText?: string) {
		const text = (overrideText ?? input).trim();
		if (!text || isStreaming || session.sessionEnded) return;

		if (!overrideText) setInput("");
		setError(null);
		const currentValues = Object.fromEntries(
			Object.entries(rsState.state.fields)
				.filter(([, f]) => f.filled && f.source !== "ai")
				.map(([k, f]) => [k, f.value]),
		);
		const { valuesForRequest, deferredForRequest } =
			rsState.applyDirectChatAnswer(
				text,
				pendingDirectChatFieldRef,
				currentValues,
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
				pendingDirectChatFieldRef.current =
					inferDirectChatFieldFromAssistant(assistantText);

				if (capturedSessionId) {
					rs.setIsExtracting(true);
					const nonce = rs.beginExtraction();
					await rs.runPostTurnExtraction(capturedSessionId, nonce);
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
				rsState.applyExtraction({
					completeness: 0,
					accepted_completeness: rsState.completeness,
					discovery_completeness: 0,
					fields: {
						[key]: {
							status: "suggested",
							accepted: null,
							suggestion: { value, source: "ai" },
							filled: false,
							value: null,
							source: null,
						},
					},
				});
			},
			valuesForRequest,
			deferredForRequest,
			(key) => setActiveWorkflowField(key),
			(messageId) => msgs.setMessageBackendId(assistantId, messageId),
			(choices) => msgs.setMessageChoices(assistantId, choices),
			(cleanText) => msgs.replaceMessageText(assistantId, cleanText),
		);
	}

	function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
		if (e.key === "Enter" && !e.shiftKey) {
			e.preventDefault();
			void handleSend();
		}
	}

	async function handleGenerateFull() {
		if (!session.sessionId) {
			setError("No active session — please send a message first.");
			return;
		}
		setIsDownloadingRs(true);
		try {
			await rsState.flushPendingPatches();
			await downloadRsTemplateDocx(session.sessionId);
		} catch (err) {
			setError(
				err instanceof Error ? err.message : "Failed to generate document",
			);
		} finally {
			setIsDownloadingRs(false);
		}
	}

	async function handleLoadSession(sid: string) {
		const loaded = await session.loadSession(sid);
		msgs.loadMessages(loaded.messages);
		if (loaded.rsPartial) rsState.hydrateFromSession(loaded.rsPartial);
		rs.setSrsData(loaded.srsData);
		rs.setFinalAnalysis(loaded.finalAnalysis);
		rs.setFinalizingStatus(loaded.finalizingStatus);
		setActiveWorkflowField(null);
		if (loaded.finalizingStatus === "complete") setActiveTab("Analysis");
	}

	function newConversation() {
		msgs.resetMessages(t("welcome_message"));
		session.resetSession();
		rs.resetExtraction();
		rsState.reset();
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
			const filenames = [file].map((f) => f.filename).join("\n");
			rsState.applyUploadAttachments(filenames);
		}
		setUploadOpen(false);
	}

	return (
		<div className="flex h-screen overflow-hidden bg-gray-100 font-sans">
			<div className="fixed right-4 top-4 z-50 flex items-center gap-3">
				<button
					type="button"
					onClick={newConversation}
					className="flex items-center gap-1.5 rounded border border-[#4caf50] bg-[#4caf50] px-3 py-1.5 text-xs font-semibold text-white shadow-sm transition-opacity hover:opacity-90"
				>
					{t("btn.new_conversation")}
				</button>
				<LanguageSwitcher />
			</div>
			{/* ── Left panel ─────────────────────────────────── */}
			<div className="flex min-h-0 w-1/2 shrink-0 flex-col border-r border-gray-200 bg-white">
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
					onToggleVoice={async () => {
						// Turning voice ON mid-completion would race the in-flight text
						// turn / debounced field PATCHes, so the voice agent could boot
						// from stale Firestore state and re-ask answered fields. Block
						// while streaming and flush pending edits first.
						if (voice.chatMode === "text") {
							if (isStreaming) return;
							await rsState.flushPendingPatches();
						}
						voice.handleToggleVoice(session.sessionId, session.setSessionId);
					}}
				/>

				<ChatTranscript
					messages={msgs.messages}
					sessionId={session.sessionId}
					bottomRef={bottomRef}
					onFeedback={(id, vote) =>
						msgs.handleFeedback(id, vote, session.sessionId, setError)
					}
					onFeedbackComment={(id, comment) =>
						msgs.handleFeedbackComment(id, comment, session.sessionId, setError)
					}
					onChoiceSelect={handleChoiceSelect}
					textareaRef={textareaRef}
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
						role="button"
						tabIndex={0}
						aria-label="Close"
						onClick={() => setUploadOpen(false)}
						onKeyDown={(e) => {
							if (e.key === "Enter" || e.key === " ") setUploadOpen(false);
						}}
					>
						<div
							className="w-80 rounded-lg border border-gray-200 bg-white p-5 shadow-xl"
							onClick={(e) => e.stopPropagation()}
							onKeyDown={(e) => e.stopPropagation()}
						>
							<div className="mb-3 flex items-center justify-between">
								<span className="text-sm font-semibold text-gray-800">
									{t("modal.attach_file")}
								</span>
								<button
									type="button"
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
					rsState={rsState.state}
					rsCompleteness={rsState.completeness}
					onFieldChange={rsState.setUserField}
					onAcceptSuggestion={rsState.acceptSuggestion}
					onDismissSuggestion={rsState.dismissSuggestion}
					sessionId={session.sessionId}
					onGenerateFull={handleGenerateFull}
					isDownloadingRs={isDownloadingRs}
					srsData={rs.srsData}
					finalizingStatus={rs.finalizingStatus}
					finalAnalysis={rs.finalAnalysis}
					isExtracting={rs.isExtracting}
					recentlyChangedKeys={rsState.recentlyChangedKeys}
					clearChangedKey={rsState.clearChangedKey}
					clearAllChangedKeys={rsState.clearAllChangedKeys}
				/>
			</div>

			{error && <ErrorToast message={error} onDismiss={() => setError(null)} />}
		</div>
	);
}
