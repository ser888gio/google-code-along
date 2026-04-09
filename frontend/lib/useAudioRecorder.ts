"use client";

import { useCallback, useRef, useState } from "react";

export interface UseAudioRecorderReturn {
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
  onAudioData: (pcmData: ArrayBuffer) => void
): UseAudioRecorderReturn {
  const [isRecording, setIsRecording] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const audioContextRef = useRef<AudioContext | null>(null);
  const workletNodeRef = useRef<AudioWorkletNode | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const sourceRef = useRef<MediaStreamAudioSourceNode | null>(null);

  const startRecording = useCallback(async () => {
    try {
      setError(null);

      // Request mic permission
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          sampleRate: 16000,       // Hint — browser may ignore
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      streamRef.current = stream;

      // Create AudioContext (browser may use 44.1/48 kHz regardless of hint)
      const audioContext = new AudioContext({ sampleRate: 16000 });
      audioContextRef.current = audioContext;

      // Load the PCM recorder worklet
      await audioContext.audioWorklet.addModule("/pcm-recorder-processor.js");

      const workletNode = new AudioWorkletNode(audioContext, "pcm-recorder-processor");
      workletNodeRef.current = workletNode;

      // Handle PCM chunks from the worklet
      workletNode.port.onmessage = (event) => {
        if (event.data.type === "audio") {
          onAudioData(event.data.data);
        }
      };

      // Connect mic → worklet
      const source = audioContext.createMediaStreamSource(stream);
      sourceRef.current = source;
      source.connect(workletNode);
      // Don't connect worklet to destination — we don't want to hear our own voice

      // Tell the worklet to start capturing
      workletNode.port.postMessage({ command: "start" });
      setIsRecording(true);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to start recording";
      setError(message);
      console.error("[useAudioRecorder] startRecording failed:", err);
    }
  }, [onAudioData]);

  const stopRecording = useCallback(() => {
    // Tell worklet to stop and flush
    if (workletNodeRef.current) {
      workletNodeRef.current.port.postMessage({ command: "stop" });
      workletNodeRef.current.disconnect();
      workletNodeRef.current = null;
    }

    // Disconnect source
    if (sourceRef.current) {
      sourceRef.current.disconnect();
      sourceRef.current = null;
    }

    // Stop all mic tracks
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    }

    // Close AudioContext
    if (audioContextRef.current) {
      audioContextRef.current.close();
      audioContextRef.current = null;
    }

    setIsRecording(false);
  }, []);

  return { isRecording, startRecording, stopRecording, error };
}
