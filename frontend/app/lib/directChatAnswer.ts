/**
 * Pure helpers for detecting and capturing direct-chat field answers.
 * These functions have no React state dependencies and are shared between
 * useRsState and useVoiceMode.
 */

import {
	DEFERRED_DIRECT_ANSWER_PATTERNS,
	DIRECT_CHAT_FIELD_KEYS,
	type DirectChatFieldKey,
} from "../generated/rsSchema";

export type { DirectChatFieldKey };

function normalizeForMatch(value: string): string {
	return (
		value
			.toLowerCase()
			.normalize("NFD")
			// biome-ignore lint/suspicious/noMisleadingCharacterClass: intentional U+0300–U+036F diacritic strip
			.replace(/[̀-ͯ]/g, "")
			.replace(/\s+/g, " ")
			.trim()
	);
}

export function asDirectChatFieldKey(key: string): DirectChatFieldKey | null {
	return (DIRECT_CHAT_FIELD_KEYS as readonly string[]).includes(key)
		? (key as DirectChatFieldKey)
		: null;
}

function isDeferredDirectAnswer(text: string): boolean {
	const normalized = normalizeForMatch(text);
	return DEFERRED_DIRECT_ANSWER_PATTERNS.some((p) =>
		new RegExp(p).test(normalized),
	);
}

function cleanDirectAnswerValue(text: string): string {
	return text
		.trim()
		.replace(/^(je to|it's|it is|jmenuje se|bude to)\s+/i, "")
		.replace(/[.。]+$/, "")
		.trim();
}

function isPlausibleDirectAnswer(text: string): boolean {
	const v = cleanDirectAnswerValue(text);
	return (
		v.length > 0 && v.length <= 80 && !v.includes("\n") && !v.includes("?")
	);
}

export function resolveDirectChatAnswer(
	text: string,
	pendingKey: DirectChatFieldKey,
	currentValues: Record<string, string>,
	deferredKeys: DirectChatFieldKey[],
):
	| { action: "defer"; nextDeferred: DirectChatFieldKey[] }
	| {
			action: "apply";
			value: string;
			nextValues: Record<string, string>;
			nextDeferred: DirectChatFieldKey[];
	  } {
	if (isDeferredDirectAnswer(text) || !isPlausibleDirectAnswer(text)) {
		return {
			action: "defer",
			nextDeferred: Array.from(new Set([...deferredKeys, pendingKey])),
		};
	}
	const value = cleanDirectAnswerValue(text);
	return {
		action: "apply",
		value,
		nextValues: { ...currentValues, [pendingKey]: value },
		nextDeferred: deferredKeys.filter((f) => f !== pendingKey),
	};
}
