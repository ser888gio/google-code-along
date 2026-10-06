"use client";

import type { ChatMode } from "../hooks/useVoiceMode";
import { useLocale } from "../i18n/LocaleContext";

export default function ChatHeader({
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
