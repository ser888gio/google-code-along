"use client";

import type { ChatMode } from "../hooks/useVoiceMode";
import { useLocale } from "../i18n/LocaleContext";

export default function ChatInput({
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

	return (
		<div className="shrink-0 border-t border-gray-200 p-3">
			{chatMode === "voice" ? (
				<VoiceControls
					wsConnectionState={wsConnectionState}
					isRecording={isRecording}
					isPlaying={isPlaying}
					sessionEnded={sessionEnded}
					recorderError={recorderError}
					onMicToggle={onMicToggle}
				/>
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

function voiceStatusKey({
	isRecording,
	isPlaying,
	isVoiceConnected,
	sessionEnded,
}: {
	isRecording: boolean;
	isPlaying: boolean;
	isVoiceConnected: boolean;
	sessionEnded: boolean;
}): string {
	if (isRecording) return "voice.listening";
	if (isPlaying) return "voice.ai_speaking";
	if (!isVoiceConnected) return "voice.connecting";
	return sessionEnded ? "voice.chat_ended" : "voice.tap_to_speak";
}

function micButtonClass(isRecording: boolean, canSpeak: boolean): string {
	if (isRecording)
		return "bg-red-500 text-white shadow-lg shadow-red-200 animate-pulse";
	if (canSpeak) return "bg-[#4a6659] text-white hover:opacity-90";
	return "bg-gray-300 text-gray-500 cursor-not-allowed";
}

function VoiceControls({
	wsConnectionState,
	isRecording,
	isPlaying,
	sessionEnded,
	recorderError,
	onMicToggle,
}: {
	wsConnectionState: string;
	isRecording: boolean;
	isPlaying: boolean;
	sessionEnded: boolean;
	recorderError: string | null;
	onMicToggle: () => void;
}) {
	const { t } = useLocale();
	const isVoiceConnected = wsConnectionState === "connected";
	const canSpeak = isVoiceConnected && !sessionEnded;

	return (
		<div className="flex flex-col items-center gap-2">
			{wsConnectionState === "connecting" && (
				<p className="text-xs text-yellow-600">{t("voice.connecting")}</p>
			)}
			{wsConnectionState === "error" && (
				<p className="text-xs text-red-600">{t("voice.conn_failed")}</p>
			)}
			{recorderError && <p className="text-xs text-red-600">{recorderError}</p>}
			<div className="flex items-center gap-3">
				<button
					type="button"
					onClick={onMicToggle}
					disabled={!canSpeak}
					title={isRecording ? "Stop speaking" : "Start speaking"}
					className={`flex h-12 w-12 items-center justify-center rounded-full transition-all ${micButtonClass(
						isRecording,
						canSpeak,
					)}`}
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
					{t(
						voiceStatusKey({
							isRecording,
							isPlaying,
							isVoiceConnected,
							sessionEnded,
						}),
					)}
				</span>
			</div>
		</div>
	);
}
