"use client";

import { useCallback, useRef, useState } from "react";

interface UseAudioPlayerReturn {
  /** Whether audio is currently being played */
  isPlaying: boolean;
  /** Initialize the player (must be called after user gesture) */
  init: () => Promise<void>;
  /** Enqueue a chunk of PCM audio (Int16, 24 kHz mono) for playback */
  enqueue: (pcmData: ArrayBuffer) => void;
  /** Signal that no more audio chunks will arrive — play until buffer drains */
  drain: () => void;
  /** Stop playback immediately and clear buffer */
  stop: () => void;
  /** Any error that occurred */
  error: string | null;
}

/**
 * Hook that wraps the AudioWorklet-based PCM player.
 *
 * Plays back PCM audio chunks (24 kHz, 16-bit mono) received from the
 * server through the `pcm-player-processor.js` worklet.
 *
 * Must call `init()` in response to a user gesture (click) to satisfy
 * browser autoplay policies.
 */
export function useAudioPlayer(): UseAudioPlayerReturn {
  const [isPlaying, setIsPlaying] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const audioContextRef = useRef<AudioContext | null>(null);
  const workletNodeRef = useRef<AudioWorkletNode | null>(null);
  const initializedRef = useRef(false);

  const init = useCallback(async () => {
    if (initializedRef.current) return;

    try {
      setError(null);

      // 24 kHz to match the server's output PCM rate
      const audioContext = new AudioContext({ sampleRate: 24000 });
      audioContextRef.current = audioContext;

      await audioContext.audioWorklet.addModule("/pcm-player-processor.js");

      const workletNode = new AudioWorkletNode(audioContext, "pcm-player-processor");
      workletNodeRef.current = workletNode;

      // Listen for playback_complete from the worklet
      workletNode.port.onmessage = (event) => {
        if (event.data.type === "playback_complete") {
          setIsPlaying(false);
        }
      };

      // Connect worklet to speakers
      workletNode.connect(audioContext.destination);

      initializedRef.current = true;
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to init audio player";
      setError(message);
      console.error("[useAudioPlayer] init failed:", err);
    }
  }, []);

  const enqueue = useCallback((pcmData: ArrayBuffer) => {
    if (!workletNodeRef.current) {
      console.warn("[useAudioPlayer] enqueue called before init");
      return;
    }

    workletNodeRef.current.port.postMessage(
      { command: "play", data: pcmData },
      [pcmData] // Transfer ownership
    );
    setIsPlaying(true);
  }, []);

  const drain = useCallback(() => {
    if (!workletNodeRef.current) return;
    workletNodeRef.current.port.postMessage({ command: "drain" });
  }, []);

  const stop = useCallback(() => {
    if (!workletNodeRef.current) return;
    workletNodeRef.current.port.postMessage({ command: "stop" });
    setIsPlaying(false);
  }, []);

  return { isPlaying, init, enqueue, drain, stop, error };
}
