"use client";

import { useState } from "react";
import type { FormEvent } from "react";
import {
	type FinalAnalysis,
	type RsPartialData,
	type SessionRating,
	type SessionSummary,
	type SrsData,
	getAnalysis,
	getDiscoveryState,
	getFirestoreData,
	getHistory,
	getSessions,
	submitSessionFeedback,
} from "../../lib/api";

import type { Role } from "./useMessages";

export type FinalizingStatus = "idle" | "finalizing" | "complete";

interface LoadedSession {
	messages: Array<{ role: Role; text: string; message_id?: string }>;
	sessionId: string;
	rsPartial: RsPartialData | null;
	srsData: SrsData | null;
	finalAnalysis: FinalAnalysis | null;
	finalizingStatus: FinalizingStatus;
}

export function useChatSession(setError: (msg: string) => void) {
	const [sessionId, setSessionId] = useState<string | null>(null);
	const [sessionEnded, setSessionEnded] = useState(false);
	const [sessionRating, setSessionRating] = useState<SessionRating | null>(
		null,
	);
	const [sessionRatingComment, setSessionRatingComment] = useState("");
	const [isSubmittingSessionRating, setIsSubmittingSessionRating] =
		useState(false);
	const [ratingOpen, setRatingOpen] = useState(false);
	const [historyOpen, setHistoryOpen] = useState(false);
	const [historySessions, setHistorySessions] = useState<SessionSummary[]>([]);
	const [historyLoading, setHistoryLoading] = useState(false);

	function ensureSession(): string {
		if (sessionId) return sessionId;
		const newId = crypto.randomUUID();
		setSessionId(newId);
		return newId;
	}

	async function openHistory() {
		setHistoryOpen(true);
		setHistoryLoading(true);
		const sessions = await getSessions();
		setHistorySessions(sessions);
		setHistoryLoading(false);
	}

	async function loadSession(sid: string): Promise<LoadedSession> {
		const msgs = await getHistory(sid);
		setSessionId(sid);
		setSessionEnded(false);
		setSessionRating(null);
		setSessionRatingComment("");
		setHistoryOpen(false);

		const [savedDiscovery, analysisResult, fsData] = await Promise.all([
			getDiscoveryState(sid),
			getAnalysis(sid),
			getFirestoreData(sid),
		]);

		return {
			messages: msgs.map((m) => ({
				role: m.role as Role,
				text: m.text,
				message_id: m.message_id,
			})),
			sessionId: sid,
			rsPartial: savedDiscovery ?? null,
			srsData: fsData ?? null,
			finalAnalysis:
				analysisResult.status === "complete"
					? analysisResult.analysis ?? null
					: null,
			finalizingStatus:
				analysisResult.status === "complete" ? "complete" : "idle",
		};
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
			setError(
				err instanceof Error ? err.message : "Could not save session rating",
			);
		} finally {
			setIsSubmittingSessionRating(false);
		}
	}

	function openSessionRating(isStreaming: boolean, chatMode: string) {
		if (!sessionId || isStreaming) return;
		setRatingOpen(true);
	}

	function resetSession(welcomeText: string) {
		setSessionId(null);
		setSessionEnded(false);
		setSessionRating(null);
		setSessionRatingComment("");
		setRatingOpen(false);
		setHistoryOpen(false);
	}

	return {
		sessionId,
		setSessionId,
		sessionEnded,
		setSessionEnded,
		sessionRating,
		setSessionRating,
		sessionRatingComment,
		setSessionRatingComment,
		isSubmittingSessionRating,
		ratingOpen,
		setRatingOpen,
		historyOpen,
		setHistoryOpen,
		historySessions,
		historyLoading,
		ensureSession,
		openHistory,
		loadSession,
		handleSessionRatingSubmit,
		openSessionRating,
		resetSession,
	};
}
