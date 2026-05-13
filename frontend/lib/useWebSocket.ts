"use client";

import { useCallback, useEffect, useRef, useState } from "react";

const WS_URL = process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8080";

type ConnectionState = "disconnected" | "connecting" | "connected" | "error";

interface WsTextMessage {
  type: "text";
  text: string;
}

interface WsUserTranscriptMessage {
  type: "user_transcript";
  text: string;
}

interface WsUserTranscriptPartialMessage {
  type: "user_transcript_partial";
  text: string;
}

interface WsTurnCompleteMessage {
  type: "turn_complete";
  finalizing?: boolean;
}

interface WsErrorMessage {
  type: "error";
  message: string;
}

export type WsServerMessage = WsTextMessage | WsUserTranscriptMessage | WsUserTranscriptPartialMessage | WsTurnCompleteMessage | WsErrorMessage;

interface UseWebSocketReturn {
  /** Current connection state */
  connectionState: ConnectionState;
  /** Connect to the bidi WebSocket */
  connect: (userId: string, sessionId: string) => void;
  /** Disconnect from the WebSocket */
  disconnect: () => void;
  /** Send raw PCM audio bytes to the server */
  sendAudio: (pcmData: ArrayBuffer) => void;
  /** Send a text message to the server */
  sendText: (text: string) => void;
}

/**
 * Hook for managing the bidirectional WebSocket connection to the backend.
 *
 * Handles:
 * - Connection lifecycle (connect/disconnect/reconnect)
 * - Sending binary PCM audio frames and text JSON frames
 * - Receiving binary audio (→ onAudioData) and text messages (→ onMessage)
 */
export function useWebSocket(options: {
  /** Called when binary audio data is received from the server (PCM 24kHz) */
  onAudioData: (pcmData: ArrayBuffer) => void;
  /** Called when a text/JSON message is received */
  onMessage: (msg: WsServerMessage) => void;
  /** Called when connection state changes */
  onConnectionChange?: (state: ConnectionState) => void;
}): UseWebSocketReturn {
  const { onAudioData, onMessage, onConnectionChange } = options;

  const [connectionState, setConnectionState] = useState<ConnectionState>("disconnected");
  const wsRef = useRef<WebSocket | null>(null);

  // Keep callback refs stable to avoid reconnect loops
  const onAudioDataRef = useRef(onAudioData);
  const onMessageRef = useRef(onMessage);
  const onConnectionChangeRef = useRef(onConnectionChange);

  useEffect(() => { onAudioDataRef.current = onAudioData; }, [onAudioData]);
  useEffect(() => { onMessageRef.current = onMessage; }, [onMessage]);
  useEffect(() => { onConnectionChangeRef.current = onConnectionChange; }, [onConnectionChange]);

  const updateState = useCallback((state: ConnectionState) => {
    setConnectionState(state);
    onConnectionChangeRef.current?.(state);
  }, []);

  const connect = useCallback((userId: string, sessionId: string) => {
    // Close existing connection if any
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }

    updateState("connecting");

    const url = `${WS_URL}/ws/${encodeURIComponent(userId)}/${encodeURIComponent(sessionId)}`;
    const ws = new WebSocket(url);
    ws.binaryType = "arraybuffer";
    wsRef.current = ws;

    ws.onopen = () => {
      updateState("connected");
    };

    ws.onclose = () => {
      wsRef.current = null;
      updateState("disconnected");
    };

    ws.onerror = (event) => {
      console.error("[useWebSocket] Error:", event);
      updateState("error");
    };

    ws.onmessage = (event) => {
      if (event.data instanceof ArrayBuffer) {
        // Binary frame = PCM audio from the server
        onAudioDataRef.current(event.data);
      } else if (typeof event.data === "string") {
        // Text frame = JSON message
        try {
          const msg: WsServerMessage = JSON.parse(event.data);
          onMessageRef.current(msg);
        } catch (err) {
          console.error("[useWebSocket] Failed to parse message:", err);
        }
      }
    };
  }, [updateState]);

  const disconnect = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    updateState("disconnected");
  }, [updateState]);

  const sendAudio = useCallback((pcmData: ArrayBuffer) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(pcmData);
    }
  }, []);

  const sendText = useCallback((text: string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "text", text }));
    }
  }, []);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, []);

  return { connectionState, connect, disconnect, sendAudio, sendText };
}
