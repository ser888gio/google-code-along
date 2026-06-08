"use client";

import { useCallback, useMemo, useRef, useState } from "react";
import {
	type FieldSource,
	type RsField,
	type RsPartialData,
	type RsState,
	patchDirectFields,
} from "../../lib/api";
import { REQUIRED_FIELD_KEYS } from "../generated/rsSchema";
import {
	type DirectChatFieldKey,
	resolveDirectChatAnswer,
} from "../lib/directChatAnswer";

// ─── Completeness ─────────────────────────────────────────────────────────────

function computeCompleteness(fields: Record<string, RsField>): number {
	const filled = REQUIRED_FIELD_KEYS.filter((k) => fields[k]?.filled).length;
	return Math.round((filled / REQUIRED_FIELD_KEYS.length) * 100);
}

// ─── Value normalisation (for suggestion dedup) ───────────────────────────────

function normalizeValue(v: string): string {
	return v.trim().replace(/\s+/g, " ").toLowerCase();
}

// ─── Server partial → RsField conversion ─────────────────────────────────────

function toRsField(
	entry: RsPartialData["fields"][string],
	now: number,
): RsField {
	return {
		value: entry.value ?? "",
		filled: entry.filled,
		source:
			(entry.source as FieldSource | null) ?? (entry.filled ? "ai" : null),
		updatedAt: now,
	};
}

// ─── Merge rule ───────────────────────────────────────────────────────────────
//
// Applied when AI extraction (or a PATCH response) arrives.
// Rules:
//   - incoming not filled  → never erase an existing value; no-op
//   - local not filled     → overwrite freely with source='ai'
//   - local filled, values equal (normalised) → clear stale suggestion; no-op
//   - local filled, values differ, not previously dismissed → set pendingSuggestion
//   - local filled, values differ, previously dismissed → no-op

function applyMergeRule(
	prev: RsField | undefined,
	incomingEntry: RsPartialData["fields"][string],
	now: number,
): RsField | undefined {
	if (!incomingEntry.filled) return undefined; // no-op signal

	const incomingValue = incomingEntry.value ?? "";

	if (!prev?.filled) {
		// Field was empty — still show as a suggestion; user must accept
		const dismissed = prev?.dismissedSuggestions ?? [];
		if (
			dismissed.some((d) => normalizeValue(d) === normalizeValue(incomingValue))
		) {
			return undefined; // already rejected this exact value
		}
		return {
			value: "",
			filled: false,
			source: null,
			updatedAt: now,
			pendingSuggestion: { value: incomingValue, receivedAt: now },
		};
	}

	// Field already has a value
	if (normalizeValue(incomingValue) === normalizeValue(prev.value)) {
		// Same value — clear any stale suggestion, no other change
		if (!prev.pendingSuggestion) return undefined; // truly no-op
		return { ...prev, pendingSuggestion: undefined };
	}

	// Different value — check dismissed list
	const dismissed = prev.dismissedSuggestions ?? [];
	if (
		dismissed.some((d) => normalizeValue(d) === normalizeValue(incomingValue))
	) {
		return undefined; // user already rejected this exact value
	}

	// Set suggestion
	return {
		...prev,
		pendingSuggestion: { value: incomingValue, receivedAt: now },
	};
}

// ─── Hook ─────────────────────────────────────────────────────────────────────

export function useRsState(sessionId: string | null) {
	const [fields, setFields] = useState<Record<string, RsField>>({});
	const [deferredKeys, setDeferredKeys] = useState<DirectChatFieldKey[]>([]);
	const [recentlyChangedKeys, setRecentlyChangedKeys] = useState<Set<string>>(
		new Set(),
	);

	// Mirrors `fields` synchronously so applyExtraction can diff without a functional updater.
	// Safe because applyExtraction is always called from async (network) contexts.
	const latestFieldsRef = useRef<Record<string, RsField>>({});
	latestFieldsRef.current = fields;

	// Per-key debounce timers
	const debounceRefs = useRef<Map<string, ReturnType<typeof setTimeout>>>(
		new Map(),
	);
	// Values waiting to be PATCHed (pending debounce)
	const pendingPatchValuesRef = useRef<Map<string, string>>(new Map());

	const completeness = useMemo(() => computeCompleteness(fields), [fields]);

	const state: RsState = useMemo(
		() => ({ fields, completeness }),
		[fields, completeness],
	);

	// ── applyExtraction ──────────────────────────────────────────────────────────
	// Called after every AI extraction and after every PATCH response.

	const applyExtraction = useCallback((partial: RsPartialData) => {
		const now = Date.now();
		const prev = latestFieldsRef.current;
		const next = { ...prev };
		const newlyChanged: string[] = [];
		let changed = false;
		for (const [key, entry] of Object.entries(partial.fields)) {
			const result = applyMergeRule(prev[key], entry, now);
			if (result !== undefined) {
				next[key] = result;
				changed = true;
				newlyChanged.push(key);
			}
		}
		if (changed) {
			latestFieldsRef.current = next;
			setFields(next);
		}
		if (newlyChanged.length > 0) {
			setRecentlyChangedKeys((prev) => {
				const nextSet = new Set(prev);
				for (const k of newlyChanged) nextSet.add(k);
				return nextSet;
			});
		}
	}, []);

	// ── setUserField ─────────────────────────────────────────────────────────────
	// Immediate optimistic update; debounced PATCH after 600ms.

	const setUserField = useCallback(
		(key: string, value: string) => {
			const now = Date.now();
			setFields((prev) => ({
				...prev,
				[key]: {
					value,
					filled: value.trim() !== "",
					source: value.trim() !== "" ? "user" : null,
					updatedAt: now,
					pendingSuggestion: undefined, // typing clears any pending suggestion
					dismissedSuggestions: prev[key]?.dismissedSuggestions,
				},
			}));

			const existing = debounceRefs.current.get(key);
			if (existing) clearTimeout(existing);
			pendingPatchValuesRef.current.set(key, value);
			debounceRefs.current.set(
				key,
				setTimeout(async () => {
					debounceRefs.current.delete(key);
					pendingPatchValuesRef.current.delete(key);
					if (!sessionId) return;
					const merged = await patchDirectFields(sessionId, { [key]: value });
					if (merged) applyExtraction(merged);
				}, 600),
			);
		},
		[sessionId, applyExtraction],
	);

	// ── acceptSuggestion ─────────────────────────────────────────────────────────

	const acceptSuggestion = useCallback(
		(key: string) => {
			let accepted = "";
			setFields((prev) => {
				const field = prev[key];
				if (!field?.pendingSuggestion) return prev;
				accepted = field.pendingSuggestion.value;
				return {
					...prev,
					[key]: {
						...field,
						value: accepted,
						filled: accepted.trim() !== "",
						source: "user" as FieldSource,
						updatedAt: Date.now(),
						pendingSuggestion: undefined,
					},
				};
			});
			// Persist immediately (no debounce — explicit user action)
			if (sessionId && accepted) {
				void patchDirectFields(sessionId, { [key]: accepted }).then(
					(merged) => {
						if (merged) applyExtraction(merged);
					},
				);
			}
		},
		[sessionId, applyExtraction],
	);

	// ── dismissSuggestion ────────────────────────────────────────────────────────

	const dismissSuggestion = useCallback(
		(key: string) => {
			let keptValue = "";
			setFields((prev) => {
				const field = prev[key];
				if (!field?.pendingSuggestion) return prev;
				keptValue = field.value;
				const dismissed = field.dismissedSuggestions ?? [];
				return {
					...prev,
					[key]: {
						...field,
						pendingSuggestion: undefined,
						dismissedSuggestions: [...dismissed, field.pendingSuggestion.value],
					},
				};
			});
			// Always PATCH — empty string explicitly clears the field on the backend,
			// preventing the AI-extracted value from winning at export time.
			if (sessionId) {
				void patchDirectFields(sessionId, { [key]: keptValue }).then(
					(merged) => {
						if (merged) applyExtraction(merged);
					},
				);
			}
		},
		[sessionId, applyExtraction],
	);

	// ── clearChangedKey / clearAllChangedKeys ────────────────────────────────────

	const clearChangedKey = useCallback((key: string) => {
		setRecentlyChangedKeys((prev) => {
			if (!prev.has(key)) return prev;
			const next = new Set(prev);
			next.delete(key);
			return next;
		});
	}, []);

	const clearAllChangedKeys = useCallback(() => {
		setRecentlyChangedKeys((prev) => (prev.size === 0 ? prev : new Set()));
	}, []);

	// ── applyDirectChatAnswer ────────────────────────────────────────────────────
	// Called when user sends a message that answers an explicitly-asked direct field.

	const applyDirectChatAnswer = useCallback(
		(
			text: string,
			pendingRef: React.RefObject<DirectChatFieldKey | null>,
			currentValues: Record<string, string>,
		): {
			valuesForRequest: Record<string, string>;
			deferredForRequest: DirectChatFieldKey[];
		} => {
			const pendingKey = pendingRef.current;
			if (!pendingKey || (fields[pendingKey]?.value ?? "").trim()) {
				return {
					valuesForRequest: currentValues,
					deferredForRequest: deferredKeys,
				};
			}
			pendingRef.current = null;
			const resolution = resolveDirectChatAnswer(
				text,
				pendingKey,
				currentValues,
				deferredKeys,
			);
			if (resolution.action === "defer") {
				setDeferredKeys(resolution.nextDeferred);
				return {
					valuesForRequest: currentValues,
					deferredForRequest: resolution.nextDeferred,
				};
			}
			setDeferredKeys(resolution.nextDeferred);
			const now = Date.now();
			setFields((prev) => ({
				...prev,
				[pendingKey]: {
					value: resolution.value,
					filled: true,
					source: "user" as FieldSource,
					updatedAt: now,
					pendingSuggestion: undefined,
					dismissedSuggestions: prev[pendingKey]?.dismissedSuggestions,
				},
			}));
			if (sessionId) {
				void patchDirectFields(sessionId, {
					[pendingKey]: resolution.value,
				}).then((merged) => {
					if (merged) applyExtraction(merged);
				});
			}
			return {
				valuesForRequest: resolution.nextValues,
				deferredForRequest: resolution.nextDeferred,
			};
		},
		[fields, deferredKeys, sessionId, applyExtraction],
	);

	// ── applyUploadAttachments ───────────────────────────────────────────────────

	const applyUploadAttachments = useCallback(
		(filenames: string) => {
			const now = Date.now();
			setFields((prev) => ({
				...prev,
				attachments: {
					value: filenames,
					filled: filenames.trim() !== "",
					source: "upload" as FieldSource,
					updatedAt: now,
					pendingSuggestion: undefined,
					dismissedSuggestions: prev.attachments?.dismissedSuggestions,
				},
			}));
			if (sessionId) {
				void patchDirectFields(sessionId, { attachments: filenames }).then(
					(merged) => {
						if (merged) applyExtraction(merged);
					},
				);
			}
		},
		[sessionId, applyExtraction],
	);

	// ── hydrateFromSession ───────────────────────────────────────────────────────

	const hydrateFromSession = useCallback((partial: RsPartialData) => {
		const now = Date.now();
		const hydrated: Record<string, RsField> = {};
		for (const [key, entry] of Object.entries(partial.fields)) {
			if (entry.filled) hydrated[key] = toRsField(entry, now);
		}
		setFields(hydrated);
		setDeferredKeys([]);
	}, []);

	// ── flushPendingPatches ──────────────────────────────────────────────────────
	// Cancels all pending debounce timers and immediately PATCHes their values.
	// Call before any action that reads the backend state (e.g. document download).

	const flushPendingPatches = useCallback(async () => {
		const pending = [...pendingPatchValuesRef.current.entries()];
		if (!pending.length || !sessionId) return;
		for (const [key] of pending) {
			const timer = debounceRefs.current.get(key);
			if (timer) {
				clearTimeout(timer);
				debounceRefs.current.delete(key);
			}
			pendingPatchValuesRef.current.delete(key);
		}
		const patch = Object.fromEntries(pending);
		const merged = await patchDirectFields(sessionId, patch);
		if (merged) applyExtraction(merged);
	}, [sessionId, applyExtraction]);

	// ── reset ────────────────────────────────────────────────────────────────────

	const reset = useCallback(() => {
		for (const t of debounceRefs.current.values()) clearTimeout(t);
		debounceRefs.current.clear();
		pendingPatchValuesRef.current.clear();
		latestFieldsRef.current = {};
		setFields({});
		setDeferredKeys([]);
		setRecentlyChangedKeys(new Set());
	}, []);

	return {
		state,
		completeness,
		deferredKeys,
		setDeferredKeys,
		setUserField,
		acceptSuggestion,
		dismissSuggestion,
		flushPendingPatches,
		applyExtraction,
		applyDirectChatAnswer,
		applyUploadAttachments,
		hydrateFromSession,
		reset,
		recentlyChangedKeys,
		clearChangedKey,
		clearAllChangedKeys,
	};
}
