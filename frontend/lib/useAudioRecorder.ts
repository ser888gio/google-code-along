"use client";

import { useCallback, useRef, useState } from "react";

interface UseAudioRecorderReturn {
	/** Whether the recorder is actively capturing audio */
	isRecording: boolean;
	/** Start recording from the microphone */
	startRecording: () => Promise<void>;
	/** Stop recording and release mic */
	stopRecording: () => void;
	/** Any error that occurred */
	error: string | null;
}

/**
 * Hook that wraps the AudioWorklet-based PCM recorder.
 *
 * Records microphone audio, downsamples to 16 kHz mono Int16 PCM via
 * the `pcm-recorder-processor.js` worklet, and calls `onAudioData` with
 * each chunk of raw PCM bytes (ArrayBuffer).
 */
export function useAudioRecorder(
	onAudioData: (pcmData: ArrayBuffer) => void,
): UseAudioRecorderReturn {
	const [isRecording, setIsRecording] = useState(false);
	const [error, setError] = useState<string | null>(null);

	const audioContextRef = useRef<AudioContext | null>(null);
	const workletNodeRef = useRef<AudioWorkletNode | null>(null);
	const streamRef = useRef<MediaStream | null>(null);
	const sourceRef = useRef<MediaStreamAudioSourceNode | null>(null);

	// Bumped by every stop, so a start still waiting on the permission prompt
	// knows it was cancelled and releases what it opened.
	const startGenerationRef = useRef(0);
	const startingRef = useRef(false);

	const releaseDevices = useCallback(() => {
		if (workletNodeRef.current) {
			workletNodeRef.current.port.postMessage({ command: "stop" });
			workletNodeRef.current.disconnect();
			workletNodeRef.current = null;
		}
		if (sourceRef.current) {
			sourceRef.current.disconnect();
			sourceRef.current = null;
		}
		if (streamRef.current) {
			for (const track of streamRef.current.getTracks()) {
				track.stop();
			}
			streamRef.current = null;
		}
		if (audioContextRef.current) {
			audioContextRef.current.close();
			audioContextRef.current = null;
		}
	}, []);

	const startRecording = useCallback(async () => {
		if (startingRef.current || streamRef.current) return;
		startingRef.current = true;
		const generation = ++startGenerationRef.current;
		const cancelled = () => generation !== startGenerationRef.current;
		try {
			setError(null);

			const stream = await navigator.mediaDevices.getUserMedia({
				audio: {
					sampleRate: 16000, // Hint — browser may ignore
					channelCount: 1,
					echoCancellation: true,
					noiseSuppression: true,
					autoGainControl: true,
				},
			});
			streamRef.current = stream;
			if (cancelled()) {
				releaseDevices();
				return;
			}

			// Browser may use 44.1/48 kHz regardless of hint
			const audioContext = new AudioContext({ sampleRate: 16000 });
			audioContextRef.current = audioContext;

			await audioContext.audioWorklet.addModule("/pcm-recorder-processor.js");
			if (cancelled()) {
				releaseDevices();
				return;
			}

			const workletNode = new AudioWorkletNode(
				audioContext,
				"pcm-recorder-processor",
			);
			workletNodeRef.current = workletNode;

			workletNode.port.onmessage = (event) => {
				if (event.data.type === "audio") {
					onAudioData(event.data.data);
				}
			};

			const source = audioContext.createMediaStreamSource(stream);
			sourceRef.current = source;
			// Not connected to the destination, so users don't hear themselves.
			source.connect(workletNode);

			workletNode.port.postMessage({ command: "start" });
			setIsRecording(true);
		} catch (err) {
			releaseDevices();
			const message =
				err instanceof Error ? err.message : "Failed to start recording";
			setError(message);
			console.error("[useAudioRecorder] startRecording failed:", err);
		} finally {
			startingRef.current = false;
		}
	}, [onAudioData, releaseDevices]);

	const stopRecording = useCallback(() => {
		startGenerationRef.current++;
		releaseDevices();
		setIsRecording(false);
	}, [releaseDevices]);

	return { isRecording, startRecording, stopRecording, error };
}
