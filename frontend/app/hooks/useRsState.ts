"use client";

import type { RefObject } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
	type FieldSource,
	type RsField,
	type RsPartialData,
	type RsState,
	patchRsFieldState,
} from "../../lib/api";
import { REQUIRED_FIELD_KEYS } from "../generated/rsSchema";
import {
	type DirectChatFieldKey,
	resolveDirectChatAnswer,
} from "../lib/directChatAnswer";

// â”€â”€â”€ Completeness â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

export function appendAttachment(existing: string, filename: string): string {
	const names = existing.split("\n").filter((n) => n.trim());
	return names.includes(filename)
		? names.join("\n")
		: [...names, filename].join("\n");
}

function computeCompleteness(fields: Record<string, RsField>): number {
	const filled = REQUIRED_FIELD_KEYS.filter((k) => fields[k]?.filled).length;
	return Math.round((filled / REQUIRED_FIELD_KEYS.length) * 100);
}

// â”€â”€â”€ Value normalisation (for suggestion dedup) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

// â”€â”€â”€ Server partial â†’ RsField conversion â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

function toRsField(
	entry: RsPartialData["fields"][string],
	now: number,
): RsField {
	const accepted = entry.accepted;
	const suggestion = entry.suggestion;
	return {
		value: accepted?.value ?? "",
		filled: Boolean(accepted?.value),
		source: (accepted?.source as FieldSource | null) ?? null,
		acceptedAt: accepted?.accepted_at ?? null,
		updatedAt: now,
		pendingSuggestion: suggestion
			? { value: suggestion.value, receivedAt: now }
			: undefined,
		dismissedSuggestions: entry.dismissed_suggestions ?? [],
	};
}

function applyPendingManualOverride(
	current: RsField | undefined,
	pendingValue: string,
	now: number,
): RsField {
	return {
		value: pendingValue,
		filled: pendingValue.trim() !== "",
		source: pendingValue.trim() !== "" ? "user_manual" : null,
		acceptedAt: null,
		updatedAt: now,
		pendingSuggestion: undefined,
		dismissedSuggestions: current?.dismissedSuggestions ?? [],
	};
}

// â”€â”€â”€ Merge rule â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
//
// Applied when AI extraction (or a PATCH response) arrives.
// Rules:
//   - incoming not filled  â†’ never erase an existing value; no-op
//   - local not filled     â†’ overwrite freely with source='ai'
//   - local filled, values equal (normalised) â†’ clear stale suggestion; no-op
//   - local filled, values differ, not previously dismissed â†’ set pendingSuggestion
//   - local filled, values differ, previously dismissed â†’ no-op

// ---- Hook â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

// Every user decision is saved through here, so a failed save is reported once
// instead of being silently dropped at each call site.
function usePersistRsPatch(
	applyExtraction: (partial: RsPartialData) => void,
	onSaveError: () => void,
) {
	// Read through a ref so a new callback identity from the caller does not
	// recreate every persistence callback that depends on this one.
	const onSaveErrorRef = useRef(onSaveError);
	useEffect(() => {
		onSaveErrorRef.current = onSaveError;
	});

	return useCallback(
		async (sid: string, patch: Parameters<typeof patchRsFieldState>[1]) => {
			const merged = await patchRsFieldState(sid, patch);
			if (merged) applyExtraction(merged);
			else onSaveErrorRef.current();
		},
		[applyExtraction],
	);
}

export function useRsState(sessionId: string | null, onSaveError: () => void) {
	const [fields, setFields] = useState<Record<string, RsField>>({});
	const [deferredKeys, setDeferredKeys] = useState<DirectChatFieldKey[]>([]);
	const [recentlyChangedKeys, setRecentlyChangedKeys] = useState<Set<string>>(
		new Set(),
	);

	// Mirrors `fields` so applyExtraction can diff against the latest network-visible state.
	const latestFieldsRef = useRef<Record<string, RsField>>({});
	useEffect(() => {
		latestFieldsRef.current = fields;
	}, [fields]);

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

	// â”€â”€ applyExtraction â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
	// Called after every AI extraction and after every PATCH response.

	const applyExtraction = useCallback((partial: RsPartialData) => {
		const now = Date.now();
		const prev = latestFieldsRef.current;
		const next = { ...prev };
		for (const [key, entry] of Object.entries(partial.fields)) {
			next[key] = toRsField(entry, now);
		}
		for (const [key, pendingValue] of pendingPatchValuesRef.current.entries()) {
			next[key] = applyPendingManualOverride(next[key], pendingValue, now);
		}

		const newlyChanged: string[] = [];
		let changed = false;
		for (const [key, result] of Object.entries(next)) {
			if (JSON.stringify(prev[key]) !== JSON.stringify(result)) {
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

	const persist = usePersistRsPatch(applyExtraction, onSaveError);

	// â”€â”€ setUserField â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
	// Immediate optimistic update; debounced PATCH after 600ms.

	const setUserField = useCallback(
		(key: string, value: string) => {
			const now = Date.now();
			setFields((prev) => ({
				...prev,
				[key]: applyPendingManualOverride(prev[key], value, now),
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
					await persist(
						sessionId,
						value.trim()
							? {
									action: "accept",
									source: "user_manual",
									fields: { [key]: value },
								}
							: { action: "clear", keys: [key] },
					);
				}, 600),
			);
		},
		[sessionId, persist],
	);

	// â”€â”€ acceptSuggestion â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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
						source: "user_accept_suggestion" as FieldSource,
						updatedAt: Date.now(),
						pendingSuggestion: undefined,
					},
				};
			});
			// Persist immediately (no debounce â€” explicit user action)
			if (sessionId && accepted) {
				void persist(sessionId, {
					action: "accept",
					source: "user_accept_suggestion",
					fields: { [key]: accepted },
				});
			}
		},
		[sessionId, persist],
	);

	// â”€â”€ dismissSuggestion â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

	const dismissSuggestion = useCallback(
		(key: string) => {
			let dismissedValue = "";
			setFields((prev) => {
				const field = prev[key];
				if (!field?.pendingSuggestion) return prev;
				dismissedValue = field.pendingSuggestion.value;
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
			if (sessionId && dismissedValue) {
				void persist(sessionId, {
					action: "dismiss",
					fields: { [key]: dismissedValue },
				});
			}
		},
		[sessionId, persist],
	);

	// â”€â”€ clearChangedKey / clearAllChangedKeys â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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

	// â”€â”€ applyDirectChatAnswer â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
	// Called when user sends a message that answers an explicitly-asked direct field.

	const applyDirectChatAnswer = useCallback(
		(
			text: string,
			pendingRef: RefObject<DirectChatFieldKey | null>,
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
					source: "user_direct_chat" as FieldSource,
					updatedAt: now,
					pendingSuggestion: undefined,
					dismissedSuggestions: prev[pendingKey]?.dismissedSuggestions,
				},
			}));
			if (sessionId) {
				void persist(sessionId, {
					action: "accept",
					source: "user_direct_chat",
					fields: { [pendingKey]: resolution.value },
				});
			}
			return {
				valuesForRequest: resolution.nextValues,
				deferredForRequest: resolution.nextDeferred,
			};
		},
		[fields, deferredKeys, sessionId, persist],
	);

	// â”€â”€ applyUploadAttachments â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

	const applyUploadAttachments = useCallback(
		(filename: string) => {
			const value = appendAttachment(
				latestFieldsRef.current.attachments?.value ?? "",
				filename,
			);
			setFields((prev) => ({
				...prev,
				attachments: {
					value,
					filled: true,
					source: "user_upload" as FieldSource,
					updatedAt: Date.now(),
					pendingSuggestion: undefined,
					dismissedSuggestions: prev.attachments?.dismissedSuggestions,
				},
			}));
			setRecentlyChangedKeys((prev) => new Set(prev).add("attachments"));
			if (sessionId) {
				void persist(sessionId, {
					action: "accept",
					source: "user_upload",
					fields: { attachments: value },
				});
			}
		},
		[sessionId, persist],
	);

	// â”€â”€ hydrateFromSession â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

	const hydrateFromSession = useCallback((partial: RsPartialData) => {
		const now = Date.now();
		const hydrated: Record<string, RsField> = {};
		for (const [key, entry] of Object.entries(partial.fields)) {
			hydrated[key] = toRsField(entry, now);
		}
		latestFieldsRef.current = hydrated;
		setFields(hydrated);
		setDeferredKeys([]);
	}, []);

	// â”€â”€ flushPendingPatches â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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
		const acceptFields = Object.fromEntries(
			Object.entries(patch).filter(([, value]) => String(value).trim()),
		);
		const clearKeys = Object.entries(patch)
			.filter(([, value]) => !String(value).trim())
			.map(([key]) => key);
		if (Object.keys(acceptFields).length) {
			await persist(sessionId, {
				action: "accept",
				source: "user_manual",
				fields: acceptFields,
			});
		}
		if (clearKeys.length) {
			await persist(sessionId, { action: "clear", keys: clearKeys });
		}
	}, [sessionId, persist]);

	// â”€â”€ reset â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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
