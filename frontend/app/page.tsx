"use client";

import { useEffect, useRef, useState } from "react";
import {
  Box,
  Stack,
  Typography,
  IconButton,
  CircularProgress,
  Divider,
  Avatar,
  Chip,
} from "@skodaflow/web-library";
import { streamChat, downloadPdf } from "../lib/api";

// ─── Types ────────────────────────────────────────────────────────────────────

type Role = "user" | "assistant";

interface Message {
  id: string;
  role: Role;
  text: string;
  streaming?: boolean;
}

// ─── Small sub-components ────────────────────────────────────────────────────

function MessageBubble({ msg }: { msg: Message }) {
  const isUser = msg.role === "user";

  return (
    <Box
      sx={{
        display: "flex",
        flexDirection: isUser ? "row-reverse" : "row",
        alignItems: "flex-start",
        gap: 1.5,
        maxWidth: "80%",
        alignSelf: isUser ? "flex-end" : "flex-start",
      }}
    >
      <Avatar
        sx={{
          width: 36,
          height: 36,
          bgcolor: isUser ? "primary.main" : "surface.secondary",
          fontSize: 14,
          flexShrink: 0,
        }}
      >
        {isUser ? "U" : "AI"}
      </Avatar>

      <Box
        sx={{
          px: 2,
          py: 1.5,
          borderRadius: isUser ? "16px 4px 16px 16px" : "4px 16px 16px 16px",
          bgcolor: isUser ? "primary.main" : "surface.secondary",
          color: isUser ? "primary.contrastText" : "text.primary",
          maxWidth: "100%",
          wordBreak: "break-word",
          whiteSpace: "pre-wrap",
        }}
      >
        <Typography variant="body1" component="span">
          {msg.text}
          {msg.streaming && (
            <Box
              component="span"
              sx={{
                display: "inline-block",
                width: 8,
                height: 16,
                ml: 0.5,
                bgcolor: "currentColor",
                opacity: 0.7,
                verticalAlign: "middle",
                animation: "blink 1s step-end infinite",
                "@keyframes blink": {
                  "0%, 100%": { opacity: 0.7 },
                  "50%": { opacity: 0 },
                },
              }}
            />
          )}
        </Typography>
      </Box>
    </Box>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const [isDownloading, setIsDownloading] = useState(false);
  const [docReady, setDocReady] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Auto-resize textarea
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, [input]);

  function addMessage(role: Role, text: string, streaming = false): string {
    const id = crypto.randomUUID();
    setMessages((prev) => [...prev, { id, role, text, streaming }]);
    return id;
  }

  function appendToMessage(id: string, chunk: string) {
    setMessages((prev) =>
      prev.map((m) => (m.id === id ? { ...m, text: m.text + chunk } : m))
    );
  }

  function finalizeMessage(id: string) {
    setMessages((prev) =>
      prev.map((m) => (m.id === id ? { ...m, streaming: false } : m))
    );
  }

  async function handleSend() {
    const text = input.trim();
    if (!text || isStreaming) return;

    setInput("");
    setError(null);
    addMessage("user", text);
    setIsStreaming(true);

    const assistantId = addMessage("assistant", "", true);

    let fullText = "";

    await streamChat(
      text,
      sessionId,
      (chunk) => {
        fullText += chunk;
        appendToMessage(assistantId, chunk);
      },
      (id) => {
        setSessionId(id);
      },
      () => {
        finalizeMessage(assistantId);
        setIsStreaming(false);
        // Check if the RS document was generated (marker in accumulated text)
        if (fullText.includes("[GENERATE_RS]")) {
          setDocReady(true);
        }
      },
      (err) => {
        finalizeMessage(assistantId);
        setError(err);
        setIsStreaming(false);
      }
    );
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  async function handleDownloadPdf() {
    if (!sessionId) return;
    setIsDownloading(true);
    try {
      await downloadPdf(sessionId);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "PDF download failed");
    } finally {
      setIsDownloading(false);
    }
  }

  const isEmpty = messages.length === 0;

  return (
    <Box
      sx={{
        display: "flex",
        flexDirection: "column",
        height: "100vh",
        bgcolor: "background.default",
      }}
    >
      {/* ── Header ── */}
      <Box
        component="header"
        sx={{
          px: 3,
          py: 2,
          borderBottom: 1,
          borderColor: "divider",
          bgcolor: "background.paper",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          flexShrink: 0,
        }}
      >
        <Stack direction="row" alignItems="center" spacing={1.5}>
          <Avatar
            sx={{ bgcolor: "primary.main", width: 40, height: 40, fontSize: 15 }}
          >
            RS
          </Avatar>
          <Box>
            <Typography variant="h6" fontWeight={600} lineHeight={1.2}>
              RS Generator
            </Typography>
            <Typography variant="caption" color="text.secondary">
              AI Business Consultant
            </Typography>
          </Box>
        </Stack>

        <Stack direction="row" alignItems="center" spacing={1}>
          {sessionId && (
            <Chip
              label={`Session: ${sessionId.slice(0, 8)}…`}
              size="small"
              variant="outlined"
            />
          )}
          {docReady && (
            <Box
              component="button"
              onClick={handleDownloadPdf}
              disabled={isDownloading}
              sx={{
                display: "flex",
                alignItems: "center",
                gap: 1,
                px: 2,
                py: 1,
                border: "none",
                borderRadius: 2,
                bgcolor: "primary.main",
                color: "primary.contrastText",
                fontWeight: 600,
                fontSize: 14,
                cursor: isDownloading ? "not-allowed" : "pointer",
                opacity: isDownloading ? 0.7 : 1,
                transition: "opacity 0.2s",
                "&:hover": { opacity: 0.85 },
              }}
            >
              {isDownloading ? (
                <CircularProgress size={16} color="inherit" />
              ) : (
                "⬇ Download PDF"
              )}
            </Box>
          )}
        </Stack>
      </Box>

      {/* ── Message thread ── */}
      <Box
        sx={{
          flex: 1,
          overflowY: "auto",
          px: { xs: 2, sm: 4, md: 8 },
          py: 3,
        }}
      >
        {isEmpty ? (
          <Box
            sx={{
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              justifyContent: "center",
              height: "100%",
              gap: 2,
              textAlign: "center",
              color: "text.secondary",
            }}
          >
            <Typography variant="h5" fontWeight={600} color="text.primary">
              Welcome to the RS Generator
            </Typography>
            <Typography variant="body1" maxWidth={480}>
              I'm your AI Business Consultant. Describe your project idea and
              I'll guide you through creating a professional Requirement
              Specification document.
            </Typography>
            <Typography variant="body2" color="text.disabled">
              Press Enter to send · Shift+Enter for new line
            </Typography>
          </Box>
        ) : (
          <Stack spacing={2.5}>
            {messages.map((msg) => (
              <MessageBubble key={msg.id} msg={msg} />
            ))}
          </Stack>
        )}
        <div ref={bottomRef} />
      </Box>

      {/* ── Error banner ── */}
      {error && (
        <>
          <Divider />
          <Box
            sx={{
              px: 3,
              py: 1,
              bgcolor: "semantic.alert.container",
              color: "semantic.alert.onContainer",
              fontSize: 14,
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
            }}
          >
            <Typography variant="body2">{error}</Typography>
            <IconButton size="small" onClick={() => setError(null)}>
              ✕
            </IconButton>
          </Box>
        </>
      )}

      {/* ── Input area ── */}
      <Divider />
      <Box
        sx={{
          px: { xs: 2, sm: 4, md: 8 },
          py: 2,
          bgcolor: "background.paper",
          flexShrink: 0,
        }}
      >
        <Box
          sx={{
            display: "flex",
            alignItems: "flex-end",
            gap: 1,
            border: 1,
            borderColor: isStreaming ? "primary.main" : "divider",
            borderRadius: 3,
            px: 2,
            py: 1,
            transition: "border-color 0.2s",
            "&:focus-within": { borderColor: "primary.main" },
            bgcolor: "background.default",
          }}
        >
          <Box
            component="textarea"
            ref={textareaRef}
            value={input}
            onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) =>
              setInput(e.target.value)
            }
            onKeyDown={handleKeyDown}
            placeholder="Describe your project or answer the consultant's questions…"
            rows={1}
            disabled={isStreaming}
            sx={{
              flex: 1,
              resize: "none",
              border: "none",
              outline: "none",
              background: "transparent",
              fontFamily: "inherit",
              fontSize: 15,
              lineHeight: 1.6,
              color: "text.primary",
              py: 0.5,
              overflowY: "auto",
              "&::placeholder": { color: "text.disabled" },
              "&:disabled": { opacity: 0.5 },
            }}
          />

          <IconButton
            onClick={handleSend}
            disabled={!input.trim() || isStreaming}
            color="primary"
            size="medium"
            sx={{ flexShrink: 0, mb: 0.25 }}
          >
            {isStreaming ? (
              <CircularProgress size={20} color="inherit" />
            ) : (
              <Box
                component="span"
                sx={{ fontSize: 20, lineHeight: 1, display: "block" }}
              >
                ➤
              </Box>
            )}
          </IconButton>
        </Box>
      </Box>
    </Box>
  );
}
