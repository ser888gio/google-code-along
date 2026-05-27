"use client";

import { useCallback, useRef, useState } from "react";
import {
	type RsPartialData,
	type SrsData,
	extractContext,
	getFirestoreData,
} from "../../lib/api";
import { useAudioPlayer } from "../../lib/useAudioPlayer";
import { useAudioRecorder } from "../../lib/useAudioRecorder";
import { type WsServerMessage, useWebSocket } from "../../lib/useWebSocket";
import type { FinalizingStatus } from "./useChatSession";

export type ChatMode = "text" | "voice";

interface VoiceModeHandlers {
	addMessage: (
		role: "user" | "assistant",
		text: string,
		streaming?: boolean,
	) => string;
	appendToMessage: (id: string, chunk: string) => void;
	replaceMessageText: (id: string, text: string) => void;
	finalizeMessage: (id: string) => void;
	applyExtraction: (partial: RsPartialData) => void;
	setSrsData: React.Dispatch<React.SetStateAction<SrsData | null>>;
	setFinalizingStatus: React.Dispatch<React.SetStateAction<FinalizingStatus>>;
	setActiveTab: (tab: string) => void;
	setIsExtracting: React.Dispatch<React.SetStateAction<boolean>>;
	extractNonceRef: React.RefObject<number>;
	setError: (msg: string) => void;
	sessionId: string | null;
}

export function useVoiceMode(handlers: VoiceModeHandlers) {
	const [chatMode, setChatMode] = useState<ChatMode>("text");

	const audioPlayer = useAudioPlayer();

	const handleWsAudio = useCallback(
		(pcmData: ArrayBuffer) => {
			audioPlayer.enqueue(pcmData);
		},
		[audioPlayer],
	);

	const voiceTranscriptIdRef = useRef<string | null>(null);
	const voiceUserTranscriptIdRef = useRef<string | null>(null);

	// biome-ignore lint/correctness/useExhaustiveDependencies: handlers object identity changes every render; stable deps come from audioPlayer
	const handleWsMessage = useCallback(
		(msg: WsServerMessage) => {
			const {
				addMessage,
				appendToMessage,
				replaceMessageText,
				finalizeMessage,
				applyExtraction,
				setSrsData,
				setFinalizingStatus,
				setActiveTab,
				setIsExtracting,
				extractNonceRef,
				setError,
				sessionId,
			} = handlers;

			if (msg.type === "user_transcript_partial") {
				if (voiceUserTranscriptIdRef.current) {
					appendToMessage(voiceUserTranscriptIdRef.current, msg.text);
				} else {
					voiceUserTranscriptIdRef.current = addMessage("user", msg.text, true);
				}
			} else if (msg.type === "user_transcript") {
				if (voiceUserTranscriptIdRef.current) {
					replaceMessageText(voiceUserTranscriptIdRef.current, msg.text);
					finalizeMessage(voiceUserTranscriptIdRef.current);
					voiceUserTranscriptIdRef.current = null;
				}
				// If ref is null, turn_complete already finalized the message — do nothing
			} else if (msg.type === "text") {
				if (voiceUserTranscriptIdRef.current) {
					finalizeMessage(voiceUserTranscriptIdRef.current);
					voiceUserTranscriptIdRef.current = null;
				}
				if (voiceTranscriptIdRef.current) {
					appendToMessage(voiceTranscriptIdRef.current, msg.text);
				} else {
					voiceTranscriptIdRef.current = addMessage(
						"assistant",
						msg.text,
						true,
					);
				}
			} else if (msg.type === "turn_complete") {
				if (voiceUserTranscriptIdRef.current) {
					finalizeMessage(voiceUserTranscriptIdRef.current);
					voiceUserTranscriptIdRef.current = null;
				}
				if (voiceTranscriptIdRef.current) {
					finalizeMessage(voiceTranscriptIdRef.current);
					voiceTranscriptIdRef.current = null;
				}
				audioPlayer.drain();

				if (sessionId) {
					const nonce = ++extractNonceRef.current;
					setIsExtracting(true);
					Promise.all([extractContext(sessionId), getFirestoreData(sessionId)])
						.then(([partial, fsData]) => {
							if (nonce !== extractNonceRef.current) return;
							if (partial) applyExtraction(partial);
							if (fsData) setSrsData(fsData);
							setIsExtracting(false);
						})
						.catch((err) => {
							console.error("[Voice] Post-turn extraction failed:", err);
							if (nonce === extractNonceRef.current) setIsExtracting(false);
						});
				}

				if (msg.finalizing) {
					setFinalizingStatus("finalizing");
					setActiveTab("Analysis");
				}
			} else if (msg.type === "error") {
				setError(msg.message);
			}
		},
		[audioPlayer],
	);

	const ws = useWebSocket({
		onAudioData: handleWsAudio,
		onMessage: handleWsMessage,
	});

	const handleAudioChunk = useCallback(
		(pcmData: ArrayBuffer) => ws.sendAudio(pcmData),
		[ws],
	);

	const audioRecorder = useAudioRecorder(handleAudioChunk);

	async function handleToggleVoice(
		sessionId: string | null,
		setSessionId: (id: string) => void,
	) {
		if (chatMode === "voice") {
			audioRecorder.stopRecording();
			audioPlayer.stop();
			ws.disconnect();
			setChatMode("text");
			return;
		}

		setChatMode("voice");
		const sid = sessionId ?? crypto.randomUUID();
		if (!sessionId) setSessionId(sid);
		await audioPlayer.init();
		ws.connect("default_user", sid);
	}

	async function handleMicToggle() {
		if (audioRecorder.isRecording) {
			audioRecorder.stopRecording();
		} else {
			audioPlayer.stop();
			voiceTranscriptIdRef.current = null;
			voiceUserTranscriptIdRef.current = null;
			await audioRecorder.startRecording();
		}
	}

	function stopVoice() {
		audioRecorder.stopRecording();
		audioPlayer.stop();
		ws.disconnect();
		setChatMode("text");
	}

	return {
		chatMode,
		setChatMode,
		audioPlayer,
		audioRecorder,
		ws,
		handleToggleVoice,
		handleMicToggle,
		stopVoice,
	};
}
