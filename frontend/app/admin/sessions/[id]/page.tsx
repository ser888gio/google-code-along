"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import {
  AdminSessionDetail,
  AdminTranscriptMessage,
  getAdminSession,
} from "../../../../lib/api";
import MessageBubbles from "../MessageBubbles";

function formatCost(value: number): string {
  return value < 0.01 ? `$${value.toFixed(4)}` : `$${value.toFixed(2)}`;
}

function formatDate(value: string | null): string {
  if (!value) return "Unknown";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="border-b border-gray-100 py-3">
      <p className="text-[11px] font-bold uppercase tracking-widest text-gray-500">
        {label}
      </p>
      <p className="mt-1 wrap-break-word text-sm font-medium text-gray-900">{value}</p>
    </div>
  );
}

function MessageSidePanel({ message }: { message: AdminTranscriptMessage | null }) {
  if (!message) {
    return (
      <aside className="rounded border border-gray-200 bg-white px-4 py-5 text-sm text-gray-500">
        Select a message
      </aside>
    );
  }

  const toolCount = message.tool_calls.length;
  const tokenTotal =
    message.input_tokens + message.output_tokens + message.cache_read_tokens;

  return (
    <aside className="sticky top-4 rounded border border-gray-200 bg-white px-4 py-4">
      <div className="border-b border-gray-100 pb-3">
        <p className="text-[11px] font-bold uppercase tracking-widest text-gray-500">
          Message
        </p>
        <p className="mt-1 break-all font-mono text-xs text-gray-600">
          {message.message_id ?? "No message id"}
        </p>
      </div>
      <Stat label="Role" value={message.role} />
      <Stat label="Created" value={formatDate(message.created_at)} />
      <Stat label="Model" value={message.model ?? "Unknown"} />
      <Stat label="Tokens" value={tokenTotal.toLocaleString()} />
      <div className="grid grid-cols-3 gap-2 border-b border-gray-100 py-3">
        <div>
          <p className="text-[11px] font-bold uppercase tracking-widest text-gray-500">
            In
          </p>
          <p className="mt-1 text-sm font-medium">{message.input_tokens}</p>
        </div>
        <div>
          <p className="text-[11px] font-bold uppercase tracking-widest text-gray-500">
            Out
          </p>
          <p className="mt-1 text-sm font-medium">{message.output_tokens}</p>
        </div>
        <div>
          <p className="text-[11px] font-bold uppercase tracking-widest text-gray-500">
            Cache
          </p>
          <p className="mt-1 text-sm font-medium">{message.cache_read_tokens}</p>
        </div>
      </div>
      <Stat label="Cost" value={formatCost(message.cost_usd)} />
      <Stat label="Tools" value={toolCount} />
      {(message.latency_ms || message.ttft_ms || message.itl_ms) && (
        <div className="grid grid-cols-3 gap-2 border-b border-gray-100 py-3">
          <div>
            <p className="text-[11px] font-bold uppercase tracking-widest text-gray-500">
              Lat
            </p>
            <p className="mt-1 text-sm font-medium">{message.latency_ms ?? 0} ms</p>
          </div>
          <div>
            <p className="text-[11px] font-bold uppercase tracking-widest text-gray-500">
              TTFT
            </p>
            <p className="mt-1 text-sm font-medium">{message.ttft_ms ?? 0} ms</p>
          </div>
          <div>
            <p className="text-[11px] font-bold uppercase tracking-widest text-gray-500">
              ITL
            </p>
            <p className="mt-1 text-sm font-medium">{message.itl_ms ?? 0} ms</p>
          </div>
        </div>
      )}
      {message.feedback && (
        <div className="border-b border-gray-100 py-3">
          <p className="text-[11px] font-bold uppercase tracking-widest text-gray-500">
            Feedback
          </p>
          <p className="mt-1 text-sm font-semibold text-red-700">
            {message.feedback.vote.replaceAll("_", " ")}
          </p>
          {message.feedback.comment_redacted && (
            <p className="mt-2 rounded border border-red-100 bg-red-50 px-3 py-2 text-sm text-red-800">
              {message.feedback.comment_redacted}
            </p>
          )}
        </div>
      )}
      {message.cloud_trace_url && (
        <a
          href={message.cloud_trace_url}
          target="_blank"
          rel="noreferrer"
          className="mt-4 block rounded border border-[#4a6659] bg-[#4a6659] px-3 py-2 text-center text-sm font-semibold text-white hover:opacity-90"
        >
          View in Cloud Trace
        </a>
      )}
      {toolCount > 0 && (
        <details className="mt-4">
          <summary className="cursor-pointer text-sm font-semibold text-gray-700">
            Tool calls
          </summary>
          <pre className="mt-2 max-h-80 overflow-auto rounded border border-gray-200 bg-gray-50 p-3 text-xs text-gray-700">
            {JSON.stringify(message.tool_calls, null, 2)}
          </pre>
        </details>
      )}
    </aside>
  );
}

export default function AdminSessionDetailPage() {
  const params = useParams<{ id: string }>();
  const sessionId = params.id;
  const [session, setSession] = useState<AdminSessionDetail | null>(null);
  const [selectedMessageId, setSelectedMessageId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getAdminSession(sessionId)
      .then((detail) => {
        if (cancelled) return;
        setSession(detail);
        setSelectedMessageId(detail.messages[0]?.message_id ?? null);
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Could not load session");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  const selectedMessage = useMemo(
    () =>
      session?.messages.find((message) => message.message_id === selectedMessageId) ??
      session?.messages[0] ??
      null,
    [selectedMessageId, session],
  );

  return (
    <main className="min-h-screen bg-white text-gray-900">
      <header className="border-b border-gray-200 bg-gray-50">
        <div className="mx-auto flex max-w-7xl flex-col gap-4 px-5 py-5 md:flex-row md:items-end md:justify-between">
          <div className="min-w-0">
            <Link
              href="/admin/sessions?filter=thumbs_down"
              className="text-sm font-medium text-[#4a6659] hover:underline"
            >
              Back to sessions
            </Link>
            <Link
              href="/admin/metrics"
              className="ml-4 text-sm font-medium text-[#4a6659] hover:underline"
            >
              Metrics
            </Link>
            <h1 className="mt-2 truncate text-2xl font-semibold text-gray-950">
              {session?.project_name ?? sessionId}
            </h1>
            <p className="mt-1 break-all font-mono text-xs text-gray-500">
              {sessionId}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-3 text-sm text-gray-600">
            <span>{session?.message_count ?? 0} messages</span>
            <span>{formatCost(session?.cost_usd ?? 0)}</span>
            {session?.cloud_trace_url && (
              <a
                href={session.cloud_trace_url}
                target="_blank"
                rel="noreferrer"
                className="rounded border border-[#4a6659] px-3 py-2 font-semibold text-[#4a6659] hover:bg-[#edf5ef]"
              >
                View in Cloud Trace
              </a>
            )}
          </div>
        </div>
      </header>

      <section className="mx-auto grid max-w-7xl gap-5 px-5 py-5 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="min-w-0">
          {loading ? (
            <div className="rounded border border-gray-200 bg-gray-50 px-4 py-8 text-center text-gray-500">
              Loading transcript
            </div>
          ) : error ? (
            <div className="rounded border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              {error}
            </div>
          ) : session ? (
            <MessageBubbles
              messages={session.messages}
              selectedMessageId={selectedMessageId}
              onSelect={(message) => setSelectedMessageId(message.message_id ?? null)}
            />
          ) : null}
        </div>
        <MessageSidePanel message={selectedMessage} />
      </section>
    </main>
  );
}
