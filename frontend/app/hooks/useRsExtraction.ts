"use client";

import { useRef, useState } from "react";
import { extractContext, getFirestoreData, getAnalysis, RsPartialData, SrsData, FinalAnalysis } from "../../lib/api";
import { FinalizingStatus } from "./useChatSession";

export function useRsExtraction(applyExtraction: (partial: RsPartialData) => void) {
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

  async function runPostTurnExtraction(sessionId: string, nonce: number) {
    const [partial, fsData] = await Promise.all([
      extractContext(sessionId),
      getFirestoreData(sessionId),
    ]);
    if (nonce !== extractNonceRef.current) return;
    if (partial) applyExtraction(partial);
    if (fsData) setSrsData(fsData);
    setIsExtracting(false);
  }

  function resetExtraction() {
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
