"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import {
  AdminDailyMetric,
  AdminMetricsResponse,
  AdminModelMetric,
  getAdminMetrics,
} from "../../../lib/api";

const WINDOWS = [1, 7, 30, 90];

function formatCurrency(value: number): string {
  return value < 0.01 ? `$${value.toFixed(4)}` : `$${value.toFixed(2)}`;
}

function formatNumber(value: number): string {
  return new Intl.NumberFormat().format(Math.round(value));
}

function formatMs(value: number | null): string {
  if (value === null || Number.isNaN(value)) return "-";
  return `${Math.round(value)} ms`;
}

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
  }).format(date);
}

function Stat({
  label,
  value,
  subvalue,
}: {
  label: string;
  value: string;
  subvalue?: string;
}) {
  return (
    <div className="rounded border border-gray-200 bg-white px-4 py-3">
      <p className="text-[11px] font-bold uppercase tracking-widest text-gray-500">
        {label}
      </p>
      <p className="mt-2 text-xl font-semibold text-gray-950">{value}</p>
      {subvalue && <p className="mt-1 text-xs text-gray-500">{subvalue}</p>}
    </div>
  );
}

function DayBars({ days }: { days: AdminDailyMetric[] }) {
  const maxCost = Math.max(...days.map((day) => day.cost_usd), 0.001);
  const maxLatency = Math.max(
    ...days.map((day) => day.p95_latency_ms ?? 0),
    1,
  );

  return (
    <div className="rounded border border-gray-200 bg-white">
      <div className="border-b border-gray-100 px-4 py-3">
        <h2 className="text-sm font-semibold text-gray-950">Daily trend</h2>
      </div>
      <div className="overflow-x-auto px-4 py-4">
        <div className="flex min-w-[680px] items-end gap-3">
          {days.map((day) => (
            <div key={day.date} className="flex flex-1 flex-col items-center gap-2">
              <div className="flex h-32 w-full items-end justify-center gap-1">
                <div
                  className="w-5 rounded-t bg-[#4a6659]"
                  style={{ height: `${Math.max((day.cost_usd / maxCost) * 100, 3)}%` }}
                  title={`Cost ${formatCurrency(day.cost_usd)}`}
                />
                <div
                  className="w-5 rounded-t bg-[#8b5e3c]"
                  style={{
                    height: `${Math.max(((day.p95_latency_ms ?? 0) / maxLatency) * 100, 3)}%`,
                  }}
                  title={`p95 latency ${formatMs(day.p95_latency_ms)}`}
                />
              </div>
              <p className="text-xs text-gray-500">{formatDate(day.date)}</p>
            </div>
          ))}
        </div>
      </div>
      <div className="flex flex-wrap gap-4 border-t border-gray-100 px-4 py-3 text-xs text-gray-500">
        <span className="inline-flex items-center gap-2">
          <span className="h-3 w-3 rounded-sm bg-[#4a6659]" />
          Cost
        </span>
        <span className="inline-flex items-center gap-2">
          <span className="h-3 w-3 rounded-sm bg-[#8b5e3c]" />
          p95 latency
        </span>
      </div>
    </div>
  );
}

function ModelTable({ rows }: { rows: AdminModelMetric[] }) {
  return (
    <div className="overflow-hidden rounded border border-gray-200 bg-white">
      <div className="border-b border-gray-100 px-4 py-3">
        <h2 className="text-sm font-semibold text-gray-950">Models and phases</h2>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[920px] table-fixed border-collapse text-left text-sm">
          <thead className="bg-gray-50 text-[11px] font-bold uppercase tracking-widest text-gray-500">
            <tr>
              <th className="w-[26%] px-4 py-3">Model</th>
              <th className="w-[10%] px-4 py-3">Phase</th>
              <th className="w-[8%] px-4 py-3">Calls</th>
              <th className="w-[10%] px-4 py-3">Cost</th>
              <th className="w-[12%] px-4 py-3">Tokens</th>
              <th className="w-[10%] px-4 py-3">Cache</th>
              <th className="w-[12%] px-4 py-3">TTFT p95</th>
              <th className="w-[12%] px-4 py-3">Latency p95</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={8} className="px-4 py-8 text-center text-gray-500">
                  No model calls in this window
                </td>
              </tr>
            ) : (
              rows.map((row) => (
                <tr
                  key={`${row.model}:${row.phase}`}
                  className="border-t border-gray-100"
                >
                  <td className="truncate px-4 py-3 font-medium text-gray-950">
                    {row.model}
                  </td>
                  <td className="px-4 py-3 text-gray-600">{row.phase}</td>
                  <td className="px-4 py-3 text-gray-600">{formatNumber(row.calls)}</td>
                  <td className="px-4 py-3 text-gray-600">
                    {formatCurrency(row.cost_usd)}
                  </td>
                  <td className="px-4 py-3 text-gray-600">
                    {formatNumber(row.input_tokens + row.output_tokens)}
                  </td>
                  <td className="px-4 py-3 text-gray-600">
                    {formatNumber(row.cache_read_tokens)}
                  </td>
                  <td className="px-4 py-3 text-gray-600">
                    {formatMs(row.p95_ttft_ms)}
                  </td>
                  <td className="px-4 py-3 text-gray-600">
                    {formatMs(row.p95_latency_ms)}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function AdminMetricsPage() {
  const [days, setDays] = useState(7);
  const [metrics, setMetrics] = useState<AdminMetricsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getAdminMetrics(days)
      .then((data) => {
        if (!cancelled) setMetrics(data);
      })
      .catch((err) => {
        if (!cancelled) {
          setMetrics(null);
          setError(err instanceof Error ? err.message : "Could not load metrics");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [days]);

  const summary = metrics?.summary;
  const cacheRatio = useMemo(() => {
    if (!summary || summary.input_tokens <= 0) return 0;
    return summary.cache_read_tokens / summary.input_tokens;
  }, [summary]);

  return (
    <main className="min-h-screen bg-gray-50 text-gray-900">
      <header className="border-b border-gray-200 bg-white">
        <div className="mx-auto flex max-w-7xl flex-col gap-4 px-5 py-5 md:flex-row md:items-end md:justify-between">
          <div>
            <p className="text-[11px] font-bold uppercase tracking-widest text-gray-500">
              Admin
            </p>
            <h1 className="mt-1 text-2xl font-semibold text-gray-950">
              Observability
            </h1>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Link
              href="/admin/sessions"
              className="rounded border border-gray-200 bg-white px-3 py-2 text-sm font-medium text-gray-600 hover:border-gray-300"
            >
              Sessions
            </Link>
            {WINDOWS.map((windowDays) => (
              <button
                key={windowDays}
                type="button"
                onClick={() => {
                  if (days === windowDays) return;
                  setLoading(true);
                  setError(null);
                  setDays(windowDays);
                }}
                className={`rounded border px-3 py-2 text-sm font-medium ${
                  days === windowDays
                    ? "border-[#4a6659] bg-[#edf5ef] text-[#1a3a2a]"
                    : "border-gray-200 bg-white text-gray-600 hover:border-gray-300"
                }`}
              >
                {windowDays}d
              </button>
            ))}
          </div>
        </div>
      </header>

      <section className="mx-auto max-w-7xl space-y-5 px-5 py-5">
        {error && (
          <div className="rounded border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}

        {loading ? (
          <div className="rounded border border-gray-200 bg-white px-4 py-8 text-center text-gray-500">
            Loading metrics
          </div>
        ) : summary && metrics ? (
          <>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <Stat
                label="Cost"
                value={formatCurrency(summary.cost_usd)}
                subvalue={`${formatNumber(summary.assistant_messages)} LLM responses`}
              />
              <Stat
                label="First token p95"
                value={formatMs(summary.p95_ttft_ms)}
                subvalue={`p50 ${formatMs(summary.p50_ttft_ms)}`}
              />
              <Stat
                label="Response latency p95"
                value={formatMs(summary.p95_latency_ms)}
                subvalue={`p50 ${formatMs(summary.p50_latency_ms)}`}
              />
              <Stat
                label="Tokens"
                value={formatNumber(summary.input_tokens + summary.output_tokens)}
                subvalue={`${Math.round(cacheRatio * 100)}% cache read ratio`}
              />
              <Stat
                label="Sessions"
                value={formatNumber(summary.sessions)}
                subvalue={`${formatNumber(summary.messages)} messages`}
              />
              <Stat
                label="Inter-token avg"
                value={formatMs(summary.avg_itl_ms)}
                subvalue="Streaming responses"
              />
              <Stat
                label="Feedback"
                value={`${summary.thumbs_up} up / ${summary.thumbs_down} down`}
                subvalue={
                  summary.avg_session_rating
                    ? `${summary.avg_session_rating.toFixed(1)} avg session rating`
                    : "No session rating"
                }
              />
              <Stat
                label="Safety finishes"
                value={formatNumber(summary.safety_finishes)}
                subvalue="Gemini safety finish reasons"
              />
            </div>

            <DayBars days={metrics.daily} />
            <ModelTable rows={metrics.by_model} />

            <div className="rounded border border-gray-200 bg-white px-4 py-3 text-xs text-gray-500">
              Source: {metrics.source.messages_view} and {metrics.source.feedback_view}
            </div>
          </>
        ) : null}
      </section>
    </main>
  );
}
