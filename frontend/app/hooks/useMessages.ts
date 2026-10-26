"use client";

import { useState } from "react";
import {
	type FeedbackVote,
	submitFeedback,
	updateFeedbackComment,
} from "../../lib/api";

export type Role = "user" | "assistant";

export interface Message {
	id: string;
	role: Role;
	text: string;
	streaming?: boolean;
	messageId?: string;
	choices?: string[];
	feedback?: {
		vote: FeedbackVote;
		comment?: string;
		pending?: boolean;
	};
}

function makeWelcomeMessage(text: string): Message {
	return { id: "welcome", role: "assistant", text, streaming: false };
}

function updateMessageById(
	prev: Message[],
	id: string,
	updater: (m: Message) => Message,
): Message[] {
	return prev.map((m) => (m.id === id ? updater(m) : m));
}

export function useMessages(initialText: string) {
	const [messages, setMessages] = useState<Message[]>(() => [
		makeWelcomeMessage(initialText),
	]);

	function addMessage(role: Role, text: string, streaming = false): string {
		const id = crypto.randomUUID();
		setMessages((prev) => [...prev, { id, role, text, streaming }]);
		return id;
	}

	function appendToMessage(id: string, chunk: string) {
		setMessages((prev) =>
			updateMessageById(prev, id, (m) => ({ ...m, text: m.text + chunk })),
		);
	}

	function replaceMessageText(id: string, text: string) {
		setMessages((prev) => updateMessageById(prev, id, (m) => ({ ...m, text })));
	}

	function finalizeMessage(id: string) {
		setMessages((prev) =>
			updateMessageById(prev, id, (m) => ({ ...m, streaming: false })),
		);
	}

	function removeMessage(id: string) {
		setMessages((prev) => prev.filter((m) => m.id !== id));
	}

	function setMessageBackendId(id: string, messageId: string) {
		setMessages((prev) =>
			updateMessageById(prev, id, (m) => ({ ...m, messageId })),
		);
	}

	function setMessageChoices(id: string, choices: string[]) {
		setMessages((prev) =>
			updateMessageById(prev, id, (m) => ({ ...m, choices })),
		);
	}

	function clearMessageChoices(id: string) {
		setMessages((prev) =>
			updateMessageById(prev, id, (m) => ({ ...m, choices: undefined })),
		);
	}

	function resetMessages(text: string) {
		setMessages([makeWelcomeMessage(text)]);
	}

	function updateWelcomeMessage(text: string) {
		setMessages((prev) => {
			if (prev.length !== 1 || prev[0]?.id !== "welcome") return prev;
			return [makeWelcomeMessage(text)];
		});
	}

	function loadMessages(
		raw: Array<{ role: Role; text: string; message_id?: string }>,
	) {
		setMessages(
			raw.map((m) => ({
				id: crypto.randomUUID(),
				role: m.role,
				text: m.text,
				messageId: m.message_id,
			})),
		);
	}

	async function handleFeedback(
		localId: string,
		vote: FeedbackVote,
		sessionId: string | null,
		setError: (msg: string) => void,
	) {
		const target = messages.find((m) => m.id === localId);
		if (!sessionId || !target?.messageId) return;

		const previousFeedback = target.feedback;
		setMessages((prev) =>
			updateMessageById(prev, localId, (m) => ({
				...m,
				feedback: { ...(m.feedback ?? {}), vote, pending: true },
			})),
		);

		try {
			await submitFeedback(sessionId, target.messageId, vote);
			setMessages((prev) =>
				updateMessageById(prev, localId, (m) =>
					m.feedback
						? { ...m, feedback: { ...m.feedback, pending: false } }
						: m,
				),
			);
		} catch (err) {
			setMessages((prev) =>
				updateMessageById(prev, localId, (m) => ({
					...m,
					feedback: previousFeedback,
				})),
			);
			setError(err instanceof Error ? err.message : "Could not save feedback");
		}
	}

	async function handleFeedbackComment(
		localId: string,
		comment: string,
		sessionId: string | null,
		setError: (msg: string) => void,
	) {
		const target = messages.find((m) => m.id === localId);
		if (!sessionId || !target?.messageId || !target.feedback?.vote) return;

		const previousComment = target.feedback.comment;
		setMessages((prev) =>
			updateMessageById(prev, localId, (m) =>
				m.feedback
					? { ...m, feedback: { ...m.feedback, comment, pending: true } }
					: m,
			),
		);

		try {
			await updateFeedbackComment(sessionId, target.messageId, comment);
			setMessages((prev) =>
				updateMessageById(prev, localId, (m) =>
					m.feedback
						? { ...m, feedback: { ...m.feedback, pending: false } }
						: m,
				),
			);
		} catch (err) {
			setMessages((prev) =>
				updateMessageById(prev, localId, (m) =>
					m.feedback
						? {
								...m,
								feedback: {
									...m.feedback,
									comment: previousComment,
									pending: false,
								},
							}
						: m,
				),
			);
			setError(
				err instanceof Error ? err.message : "Could not save feedback comment",
			);
		}
	}

	return {
		messages,
		addMessage,
		appendToMessage,
		replaceMessageText,
		finalizeMessage,
		removeMessage,
		setMessageBackendId,
		setMessageChoices,
		clearMessageChoices,
		resetMessages,
		updateWelcomeMessage,
		loadMessages,
		handleFeedback,
		handleFeedbackComment,
	};
}
