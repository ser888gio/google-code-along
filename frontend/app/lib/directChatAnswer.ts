/**
 * Pure helpers for detecting and capturing direct-chat field answers.
 * These functions have no React state dependencies and are shared between
 * useRsState and useVoiceMode.
 */

import {
  DirectChatFieldKey,
  DIRECT_CHAT_FIELD_PATTERNS,
  DEFERRED_DIRECT_ANSWER_PATTERNS,
} from "../generated/rsSchema";

export type { DirectChatFieldKey };

function normalizeForMatch(value: string): string {
  return value.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/\s+/g, " ").trim();
}

export function inferDirectChatFieldFromAssistant(text: string): DirectChatFieldKey | null {
  const normalized = normalizeForMatch(text);
  for (const field of DIRECT_CHAT_FIELD_PATTERNS) {
    if (field.patterns.some((p) => new RegExp(p).test(normalized))) return field.key;
  }
  return null;
}

function isDeferredDirectAnswer(text: string): boolean {
  const normalized = normalizeForMatch(text);
  return DEFERRED_DIRECT_ANSWER_PATTERNS.some((p) => new RegExp(p).test(normalized));
}

function cleanDirectAnswerValue(text: string): string {
  return text.trim().replace(/^(je to|it's|it is|jmenuje se|bude to)\s+/i, "").replace(/[.。]+$/, "").trim();
}

function isPlausibleDirectAnswer(text: string): boolean {
  const v = cleanDirectAnswerValue(text);
  return v.length > 0 && v.length <= 80 && !v.includes("\n") && !v.includes("?");
}

export function resolveDirectChatAnswer(
  text: string,
  pendingKey: DirectChatFieldKey,
  currentValues: Record<string, string>,
  deferredKeys: DirectChatFieldKey[]
):
  | { action: "defer"; nextDeferred: DirectChatFieldKey[] }
  | { action: "apply"; value: string; nextValues: Record<string, string>; nextDeferred: DirectChatFieldKey[] } {
  if (isDeferredDirectAnswer(text) || !isPlausibleDirectAnswer(text)) {
    return { action: "defer", nextDeferred: Array.from(new Set([...deferredKeys, pendingKey])) };
  }
  const value = cleanDirectAnswerValue(text);
  return {
    action: "apply",
    value,
    nextValues: { ...currentValues, [pendingKey]: value },
    nextDeferred: deferredKeys.filter((f) => f !== pendingKey),
  };
}
