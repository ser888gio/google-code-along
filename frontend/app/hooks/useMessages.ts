"use client";

import { useState } from "react";
import { submitFeedback, updateFeedbackComment, FeedbackVote } from "../../lib/api";

export type Role = "user" | "assistant";

export interface Message {
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

export function makeWelcomeMessage(text: string): Message {
  return { id: "welcome", role: "assistant", text, streaming: false };
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
      prev.map((m) => (m.id === id ? { ...m, text: m.text + chunk } : m))
    );
  }

  function replaceMessageText(id: string, text: string) {
    setMessages((prev) =>
      prev.map((m) => (m.id === id ? { ...m, text } : m))
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

  function resetMessages(text: string) {
    setMessages([makeWelcomeMessage(text)]);
  }

  function loadMessages(
    raw: Array<{ role: Role; text: string; message_id?: string }>
  ) {
    setMessages(
      raw.map((m) => ({
        id: crypto.randomUUID(),
        role: m.role,
        text: m.text,
        messageId: m.message_id,
      }))
    );
  }

  async function handleFeedback(
    localId: string,
    vote: FeedbackVote,
    sessionId: string | null,
    setError: (msg: string) => void
  ) {
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
        prev.map((m) => (m.id === localId ? { ...m, feedback: previousFeedback } : m))
      );
      setError(err instanceof Error ? err.message : "Could not save feedback");
    }
  }

  async function handleFeedbackComment(
    localId: string,
    comment: string,
    sessionId: string | null,
    setError: (msg: string) => void
  ) {
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
            ? { ...m, feedback: { ...m.feedback, comment: previousComment, pending: false } }
            : m
        )
      );
      setError(err instanceof Error ? err.message : "Could not save feedback comment");
    }
  }

  return {
    messages,
    addMessage,
    appendToMessage,
    replaceMessageText,
    finalizeMessage,
    setMessageBackendId,
    resetMessages,
    loadMessages,
    handleFeedback,
    handleFeedbackComment,
  };
}
