"use client";

import { useCallback, useLayoutEffect, useRef, useState } from "react";
import {
	type RsPartialData,
	type SrsData,
	extractContext,
	getFirestoreData,
} from "../../lib/api";
import { useAudioPlayer } from "../../lib/useAudioPlayer";
import { useAudioRecorder } from "../../lib/useAudioRecorder";
import {
	type ConnectionState,
	type WsServerMessage,
	useWebSocket,
} from "../../lib/useWebSocket";
import { useLocale } from "../i18n/LocaleContext";
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
	const { locale, t } = useLocale();

	const audioPlayer = useAudioPlayer();

	const handleWsAudio = useCallback(
		(pcmData: ArrayBuffer) => {
			audioPlayer.enqueue(pcmData);
		},
		[audioPlayer],
	);

	const voiceTranscriptIdRef = useRef<string | null>(null);
	const voiceUserTranscriptIdRef = useRef<string | null>(null);
	// The final user transcript can arrive after the turn already closed the live
	// caption; it then corrects that message instead of being dropped or repeated.
	const userAwaitingFinalIdRef = useRef<string | null>(null);

	const handlersRef = useRef(handlers);
	useLayoutEffect(() => {
		handlersRef.current = handlers;
	});

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
			} = handlersRef.current;

			const closeUserCaption = () => {
				if (!voiceUserTranscriptIdRef.current) return;
				finalizeMessage(voiceUserTranscriptIdRef.current);
				userAwaitingFinalIdRef.current = voiceUserTranscriptIdRef.current;
				voiceUserTranscriptIdRef.current = null;
			};

			if (msg.type === "user_transcript_partial") {
				if (voiceUserTranscriptIdRef.current) {
					appendToMessage(voiceUserTranscriptIdRef.current, msg.text);
				} else {
					userAwaitingFinalIdRef.current = null;
					voiceUserTranscriptIdRef.current = addMessage("user", msg.text, true);
				}
			} else if (msg.type === "user_transcript") {
				const id =
					voiceUserTranscriptIdRef.current ?? userAwaitingFinalIdRef.current;
				if (id) {
					replaceMessageText(id, msg.text);
					finalizeMessage(id);
				} else {
					addMessage("user", msg.text);
				}
				voiceUserTranscriptIdRef.current = null;
				userAwaitingFinalIdRef.current = null;
			} else if (msg.type === "text") {
				closeUserCaption();
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
				closeUserCaption();
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

	// The recorder is created below the socket, so the connection callback reaches it through a ref.
	const stopAudioRef = useRef(() => {});
	const handleConnectionChange = useCallback((state: ConnectionState) => {
		if (state === "error" || state === "disconnected") stopAudioRef.current();
		// "error" keeps voice mode so its connection-failed hint stays visible.
		if (state === "disconnected") setChatMode("text");
	}, []);

	const ws = useWebSocket({
		onAudioData: handleWsAudio,
		onMessage: handleWsMessage,
		onConnectionChange: handleConnectionChange,
	});

	const handleAudioChunk = useCallback(
		(pcmData: ArrayBuffer) => ws.sendAudio(pcmData),
		[ws],
	);

	const audioRecorder = useAudioRecorder(handleAudioChunk);
	useLayoutEffect(() => {
		stopAudioRef.current = () => {
			audioRecorder.stopRecording();
			audioPlayer.stop();
		};
	});

	async function handleToggleVoice(
		sessionId: string | null,
		setSessionId: (id: string) => void,
	) {
		if (chatMode === "voice") {
			stopVoice();
			return;
		}

		if (!(await audioPlayer.init())) {
			handlersRef.current.setError(t("voice.audio_init_failed"));
			return;
		}
		setChatMode("voice");
		const sid = sessionId ?? crypto.randomUUID();
		if (!sessionId) setSessionId(sid);
		ws.connect("default_user", sid, locale);
	}

	async function handleMicToggle() {
		if (audioRecorder.isRecording) {
			audioRecorder.stopRecording();
		} else {
			audioPlayer.stop();
			voiceTranscriptIdRef.current = null;
			voiceUserTranscriptIdRef.current = null;
			userAwaitingFinalIdRef.current = null;
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
