"use client";

import { useRef, useState } from "react";
import { patchDirectFields, getSessionUploads, RsPartialData, UploadedFile } from "../../lib/api";
import {
  REQUIRED_FIELD_KEYS,
  STRICT_DIRECT_FIELD_KEYS,
  SUGGESTABLE_DIRECT_FIELD_KEYS,
  DirectChatFieldKey,
  DIRECT_CHAT_FIELD_PATTERNS,
  DEFERRED_DIRECT_ANSWER_PATTERNS,
} from "../generated/rsSchema";

// ─── Field sets ───────────────────────────────────────────────────────────────

export const DIRECT_INPUT_KEYS = new Set<string>(STRICT_DIRECT_FIELD_KEYS);
export const SUGGESTABLE_DIRECT_KEYS = new Set<string>(SUGGESTABLE_DIRECT_FIELD_KEYS);
const REQUIRED_KEYS = new Set<string>(REQUIRED_FIELD_KEYS);

// ─── Pure helpers (shared with useRsExtraction) ───────────────────────────────

function computeOptimisticCompleteness(
  rsPartial: RsPartialData | null,
  directFields: Record<string, string>
): number {
  const filled = REQUIRED_FIELD_KEYS.filter((k) => {
    if (SUGGESTABLE_DIRECT_KEYS.has(k)) return (directFields[k] ?? "").trim() !== "";
    return rsPartial?.fields[k]?.filled === true;
  }).length;
  return Math.round((filled / REQUIRED_KEYS.size) * 100);
}

export function mergePartialFields(
  prev: RsPartialData | null,
  incoming: RsPartialData,
  directFields: Record<string, string>
): RsPartialData {
  const prevFilled = Object.fromEntries(
    Object.entries(prev?.fields ?? {}).filter(
      ([k, v]) => v.filled && !incoming.fields[k]?.filled
    )
  );
  const prevDirect = Object.fromEntries(
    Object.entries(prev?.fields ?? {}).filter(
      ([k]) =>
        (DIRECT_INPUT_KEYS.has(k) ||
          (SUGGESTABLE_DIRECT_KEYS.has(k) && (directFields[k] ?? "").trim() !== "")) &&
        !incoming.fields[k]?.filled
    )
  );
  const mergedFields = { ...incoming.fields, ...prevFilled, ...prevDirect };
  const merged: RsPartialData = { completeness: 0, fields: mergedFields };
  return { completeness: computeOptimisticCompleteness(merged, directFields), fields: mergedFields };
}

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

function resolveDirectChatAnswer(
  text: string,
  pendingKey: DirectChatFieldKey,
  directFields: Record<string, string>,
  deferredDirectFields: DirectChatFieldKey[]
):
  | { action: "defer"; nextDeferred: DirectChatFieldKey[] }
  | { action: "apply"; value: string; nextDirectFields: Record<string, string>; nextDeferred: DirectChatFieldKey[] } {
  if (isDeferredDirectAnswer(text) || !isPlausibleDirectAnswer(text)) {
    return { action: "defer", nextDeferred: Array.from(new Set([...deferredDirectFields, pendingKey])) };
  }
  const value = cleanDirectAnswerValue(text);
  return {
    action: "apply",
    value,
    nextDirectFields: { ...directFields, [pendingKey]: value },
    nextDeferred: deferredDirectFields.filter((f) => f !== pendingKey),
  };
}

// ─── Hook ─────────────────────────────────────────────────────────────────────

export function useDirectFields(
  setRsPartial: React.Dispatch<React.SetStateAction<RsPartialData | null>>
) {
  const [directFields, setDirectFields] = useState<Record<string, string>>({});
  const [deferredDirectFields, setDeferredDirectFields] = useState<DirectChatFieldKey[]>([]);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  function handleDirectFieldChange(key: string, value: string, sessionId: string | null) {
    const next = { ...directFields, [key]: value };
    setDirectFields(next);
    if (value.trim()) setDeferredDirectFields((prev) => prev.filter((f) => f !== key));
    setRsPartial((prev) => (prev ? { ...prev, completeness: computeOptimisticCompleteness(prev, next) } : prev));
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(async () => {
      if (!sessionId) return;
      const merged = await patchDirectFields(sessionId, { [key]: value });
      if (merged) setRsPartial(merged);
    }, 600);
  }

  async function refreshSessionUploads(sid: string, fallbackFiles: UploadedFile[] = []) {
    const files = await getSessionUploads(sid);
    const visible = files.length > 0 ? files : fallbackFiles;
    if (visible.length === 0) return;
    const attachments = visible.map((f) => f.filename).join("\n");
    setDirectFields((prev) => (prev.attachments === attachments ? prev : { ...prev, attachments }));
    const merged = await patchDirectFields(sid, { attachments });
    if (merged) setRsPartial(merged);
  }

  function applyDirectChatAnswer(
    text: string,
    pendingRef: React.RefObject<DirectChatFieldKey | null>,
    sessionId: string | null
  ): { directFieldsForRequest: Record<string, string>; deferredFieldsForRequest: DirectChatFieldKey[] } {
    const pendingKey = pendingRef.current;
    if (!pendingKey || (directFields[pendingKey] ?? "").trim()) {
      return { directFieldsForRequest: directFields, deferredFieldsForRequest: deferredDirectFields };
    }
    pendingRef.current = null;
    const resolution = resolveDirectChatAnswer(text, pendingKey, directFields, deferredDirectFields);
    if (resolution.action === "defer") {
      setDeferredDirectFields(resolution.nextDeferred);
      return { directFieldsForRequest: directFields, deferredFieldsForRequest: resolution.nextDeferred };
    }
    setDirectFields(resolution.nextDirectFields);
    setDeferredDirectFields(resolution.nextDeferred);
    setRsPartial((prev) => ({
      completeness: prev?.completeness ?? 0,
      fields: { ...(prev?.fields ?? {}), [pendingKey]: { filled: true, value: resolution.value } },
    }));
    if (sessionId) {
      void patchDirectFields(sessionId, { [pendingKey]: resolution.value }).then((merged) => {
        if (merged) setRsPartial(merged);
      });
    }
    return { directFieldsForRequest: resolution.nextDirectFields, deferredFieldsForRequest: resolution.nextDeferred };
  }

  function resetDirectFields() {
    setDirectFields({});
    setDeferredDirectFields([]);
  }

  return {
    directFields,
    setDirectFields,
    deferredDirectFields,
    setDeferredDirectFields,
    handleDirectFieldChange,
    refreshSessionUploads,
    applyDirectChatAnswer,
    resetDirectFields,
  };
}
