"use client";

import { useRef, useState } from "react";
import {
	type FinalAnalysis,
	type RsPartialData,
	type SrsData,
	extractContext,
	getAnalysis,
	getFirestoreData,
} from "../../lib/api";
import type { FinalizingStatus } from "./useChatSession";

const POLL_INTERVAL_MS = 5000;
// ponytail: a fixed count, not backoff; three misses (~15 s) rides out a blip
// without leaving the user on the finalizing screen indefinitely.
const MAX_UNREACHABLE_POLLS = 3;

export function useRsExtraction(
	applyExtraction: (partial: RsPartialData) => void,
) {
	const [srsData, setSrsData] = useState<SrsData | null>(null);
	const [isExtracting, setIsExtracting] = useState(false);
	const [finalizingStatus, setFinalizingStatus] =
		useState<FinalizingStatus>("idle");
	const [finalAnalysis, setFinalAnalysis] = useState<FinalAnalysis | null>(
		null,
	);

	const extractNonceRef = useRef(0);
	const pollingRef = useRef<ReturnType<typeof setTimeout> | null>(null);

	function stopPolling() {
		if (pollingRef.current) clearTimeout(pollingRef.current);
		pollingRef.current = null;
	}

	// The next poll is scheduled only after the previous answer arrives, so a
	// slow backend never has requests piling up.
	function startPolling(sessionId: string) {
		stopPolling();
		let unreachableInARow = 0;
		const poll = async () => {
			const result = await getAnalysis(sessionId);
			if (pollingRef.current !== timer) return;
			const done = result.status === "complete" && result.analysis;
			unreachableInARow =
				result.status === "unreachable" ? unreachableInARow + 1 : 0;
			if (done) {
				pollingRef.current = null;
				setFinalAnalysis(done);
				setFinalizingStatus("complete");
			} else if (
				result.status === "error" ||
				unreachableInARow >= MAX_UNREACHABLE_POLLS
			) {
				pollingRef.current = null;
				setFinalizingStatus("failed");
			} else {
				timer = setTimeout(poll, POLL_INTERVAL_MS);
				pollingRef.current = timer;
			}
		};
		let timer = setTimeout(poll, POLL_INTERVAL_MS);
		pollingRef.current = timer;
		return stopPolling;
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
		stopPolling();
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
