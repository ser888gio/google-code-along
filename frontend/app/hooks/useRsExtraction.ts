"use client";

import { useRef, useState } from "react";
import { extractContext, getFirestoreData, getAnalysis, RsPartialData, SrsData, FinalAnalysis } from "../../lib/api";
import { FinalizingStatus } from "./useChatSession";
import { SUGGESTABLE_DIRECT_KEYS, mergePartialFields } from "./useDirectFields";

export function useRsExtraction() {
  const [rsPartial, setRsPartial] = useState<RsPartialData | null>(null);
  const [srsData, setSrsData] = useState<SrsData | null>(null);
  const [isExtracting, setIsExtracting] = useState(false);
  const [finalizingStatus, setFinalizingStatus] = useState<FinalizingStatus>("idle");
  const [finalAnalysis, setFinalAnalysis] = useState<FinalAnalysis | null>(null);

  const extractNonceRef = useRef(0);
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  function startPolling(sessionId: string) {
    if (pollingRef.current) clearInterval(pollingRef.current);
    pollingRef.current = setInterval(async () => {
      const result = await getAnalysis(sessionId);
      if (result.status === "complete" && result.analysis) {
        clearInterval(pollingRef.current!);
        pollingRef.current = null;
        setFinalAnalysis(result.analysis);
        setFinalizingStatus("complete");
      }
    }, 5000);
    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current);
    };
  }

  function beginExtraction(): number {
    setIsExtracting(true);
    return ++extractNonceRef.current;
  }

  async function runPostTurnExtraction(
    sessionId: string,
    currentDirectFields: Record<string, string>,
    nonce: number,
    setDirectFields: React.Dispatch<React.SetStateAction<Record<string, string>>>
  ) {
    const [partial, fsData] = await Promise.all([
      extractContext(sessionId),
      getFirestoreData(sessionId),
    ]);
    if (nonce !== extractNonceRef.current) return;
    if (partial) {
      setRsPartial((prev) => mergePartialFields(prev, partial, currentDirectFields));
      setDirectFields((prev) => {
        const updates: Record<string, string> = {};
        for (const k of SUGGESTABLE_DIRECT_KEYS) {
          if (!(prev[k] ?? "").trim() && partial.fields[k]?.filled && partial.fields[k]?.value) {
            updates[k] = partial.fields[k].value as string;
          }
        }
        return Object.keys(updates).length ? { ...prev, ...updates } : prev;
      });
    }
    if (fsData) setSrsData(fsData);
    setIsExtracting(false);
  }

  function resetExtraction() {
    setRsPartial(null);
    setSrsData(null);
    setFinalizingStatus("idle");
    setFinalAnalysis(null);
    setIsExtracting(false);
    if (pollingRef.current) {
      clearInterval(pollingRef.current);
      pollingRef.current = null;
    }
  }

  return {
    rsPartial,
    setRsPartial,
    srsData,
    setSrsData,
    isExtracting,
    setIsExtracting,
    finalizingStatus,
    setFinalizingStatus,
    finalAnalysis,
    setFinalAnalysis,
    extractNonceRef,
    beginExtraction,
    runPostTurnExtraction,
    startPolling,
    resetExtraction,
  };
}
