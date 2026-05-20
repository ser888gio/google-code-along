"use client";

import { useRef, useState, useMemo, useCallback } from "react";
import { patchDirectFields, RsPartialData, RsField, RsState, FieldSource } from "../../lib/api";
import { REQUIRED_FIELD_KEYS } from "../generated/rsSchema";
import {
  DirectChatFieldKey,
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

function toRsField(entry: RsPartialData["fields"][string], now: number): RsField {
  return {
    value: entry.value ?? "",
    filled: entry.filled,
    source: (entry.source as FieldSource | null) ?? (entry.filled ? "ai" : null),
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
  now: number
): RsField | undefined {
  if (!incomingEntry.filled) return undefined; // no-op signal

  const incomingValue = incomingEntry.value ?? "";

  if (!prev?.filled) {
    // Field was empty — overwrite directly
    return {
      value: incomingValue,
      filled: true,
      source: (incomingEntry.source as FieldSource | null) ?? "ai",
      updatedAt: now,
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
  if (dismissed.some((d) => normalizeValue(d) === normalizeValue(incomingValue))) {
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

  // Per-key debounce timers
  const debounceRefs = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());

  const completeness = useMemo(() => computeCompleteness(fields), [fields]);

  const state: RsState = useMemo(() => ({ fields, completeness }), [fields, completeness]);

  // ── applyExtraction ──────────────────────────────────────────────────────────
  // Called after every AI extraction and after every PATCH response.

  const applyExtraction = useCallback((partial: RsPartialData) => {
    const now = Date.now();
    setFields((prev) => {
      const next = { ...prev };
      let changed = false;
      for (const [key, entry] of Object.entries(partial.fields)) {
        const result = applyMergeRule(prev[key], entry, now);
        if (result !== undefined) {
          next[key] = result;
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, []);

  // ── setUserField ─────────────────────────────────────────────────────────────
  // Immediate optimistic update; debounced PATCH after 600ms.

  const setUserField = useCallback((key: string, value: string) => {
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
    debounceRefs.current.set(
      key,
      setTimeout(async () => {
        debounceRefs.current.delete(key);
        if (!sessionId) return;
        const merged = await patchDirectFields(sessionId, { [key]: value });
        if (merged) applyExtraction(merged);
      }, 600)
    );
  }, [sessionId, applyExtraction]);

  // ── acceptSuggestion ─────────────────────────────────────────────────────────

  const acceptSuggestion = useCallback((key: string) => {
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
      void patchDirectFields(sessionId, { [key]: accepted }).then((merged) => {
        if (merged) applyExtraction(merged);
      });
    }
  }, [sessionId, applyExtraction]);

  // ── dismissSuggestion ────────────────────────────────────────────────────────

  const dismissSuggestion = useCallback((key: string) => {
    setFields((prev) => {
      const field = prev[key];
      if (!field?.pendingSuggestion) return prev;
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
    // No PATCH — dismissal is client-only
  }, []);

  // ── applyDirectChatAnswer ────────────────────────────────────────────────────
  // Called when user sends a message that answers an explicitly-asked direct field.

  const applyDirectChatAnswer = useCallback((
    text: string,
    pendingRef: React.RefObject<DirectChatFieldKey | null>,
    currentValues: Record<string, string>
  ): { valuesForRequest: Record<string, string>; deferredForRequest: DirectChatFieldKey[] } => {
    const pendingKey = pendingRef.current;
    if (!pendingKey || (fields[pendingKey]?.value ?? "").trim()) {
      return { valuesForRequest: currentValues, deferredForRequest: deferredKeys };
    }
    pendingRef.current = null;
    const resolution = resolveDirectChatAnswer(text, pendingKey, currentValues, deferredKeys);
    if (resolution.action === "defer") {
      setDeferredKeys(resolution.nextDeferred);
      return { valuesForRequest: currentValues, deferredForRequest: resolution.nextDeferred };
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
      void patchDirectFields(sessionId, { [pendingKey]: resolution.value }).then((merged) => {
        if (merged) applyExtraction(merged);
      });
    }
    return { valuesForRequest: resolution.nextValues, deferredForRequest: resolution.nextDeferred };
  }, [fields, deferredKeys, sessionId, applyExtraction]);

  // ── applyUploadAttachments ───────────────────────────────────────────────────

  const applyUploadAttachments = useCallback((filenames: string) => {
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
      void patchDirectFields(sessionId, { attachments: filenames }).then((merged) => {
        if (merged) applyExtraction(merged);
      });
    }
  }, [sessionId, applyExtraction]);

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

  // ── reset ────────────────────────────────────────────────────────────────────

  const reset = useCallback(() => {
    for (const t of debounceRefs.current.values()) clearTimeout(t);
    debounceRefs.current.clear();
    setFields({});
    setDeferredKeys([]);
  }, []);

  return {
    state,
    completeness,
    deferredKeys,
    setDeferredKeys,
    setUserField,
    acceptSuggestion,
    dismissSuggestion,
    applyExtraction,
    applyDirectChatAnswer,
    applyUploadAttachments,
    hydrateFromSession,
    reset,
  };
}
