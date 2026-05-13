"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import {
  AdminSessionFilter,
  AdminSessionSummary,
  getAdminSessions,
} from "../../../lib/api";

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

export default function AdminSessionsPage() {
  const [filter, setFilter] = useState<AdminSessionFilter | undefined>(() => {
    if (typeof window === "undefined") return undefined;
    const params = new URLSearchParams(window.location.search);
    return params.get("filter") === "thumbs_down" ? "thumbs_down" : undefined;
  });
  const [sessions, setSessions] = useState<AdminSessionSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getAdminSessions(filter)
      .then((items) => {
        if (!cancelled) setSessions(items);
      })
      .catch((err) => {
        if (!cancelled) {
          setSessions([]);
          setError(err instanceof Error ? err.message : "Could not load sessions");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [filter]);

  const totalCost = useMemo(
    () => sessions.reduce((sum, session) => sum + session.cost_usd, 0),
    [sessions],
  );

  function updateFilter(next: AdminSessionFilter | undefined) {
    setFilter(next);
    setLoading(true);
    setError(null);
    const url = next ? `/admin/sessions?filter=${next}` : "/admin/sessions";
    window.history.replaceState(null, "", url);
  }

  return (
    <main className="min-h-screen bg-white text-gray-900">
      <header className="border-b border-gray-200 bg-gray-50">
        <div className="mx-auto flex max-w-7xl flex-col gap-4 px-5 py-5 md:flex-row md:items-end md:justify-between">
          <div>
            <p className="text-[11px] font-bold uppercase tracking-widest text-gray-500">
              Admin
            </p>
            <h1 className="mt-1 text-2xl font-semibold text-gray-950">
              Chat Review
            </h1>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Link
              href="/admin/metrics"
              className="rounded border border-gray-200 bg-white px-3 py-2 text-sm font-medium text-gray-600 hover:border-gray-300"
            >
              Metrics
            </Link>
            <button
              type="button"
              onClick={() => updateFilter(undefined)}
              className={`rounded border px-3 py-2 text-sm font-medium ${
                filter
                  ? "border-gray-200 bg-white text-gray-600 hover:border-gray-300"
                  : "border-[#4a6659] bg-[#edf5ef] text-[#1a3a2a]"
              }`}
            >
              All
            </button>
            <button
              type="button"
              onClick={() => updateFilter("thumbs_down")}
              className={`rounded border px-3 py-2 text-sm font-medium ${
                filter === "thumbs_down"
                  ? "border-red-300 bg-red-50 text-red-700"
                  : "border-gray-200 bg-white text-gray-600 hover:border-gray-300"
              }`}
            >
              Thumbs down
            </button>
          </div>
        </div>
      </header>

      <section className="border-b border-gray-100">
        <div className="mx-auto grid max-w-7xl gap-3 px-5 py-4 sm:grid-cols-3">
          <div>
            <p className="text-[11px] font-bold uppercase tracking-widest text-gray-500">
              Sessions
            </p>
            <p className="mt-1 text-xl font-semibold">{sessions.length}</p>
          </div>
          <div>
            <p className="text-[11px] font-bold uppercase tracking-widest text-gray-500">
              Review Cost
            </p>
            <p className="mt-1 text-xl font-semibold">{formatCost(totalCost)}</p>
          </div>
          <div>
            <p className="text-[11px] font-bold uppercase tracking-widest text-gray-500">
              Filter
            </p>
            <p className="mt-1 text-xl font-semibold">
              {filter === "thumbs_down" ? "Thumbs down" : "All sessions"}
            </p>
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-7xl px-5 py-5">
        {error && (
          <div className="mb-4 rounded border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}
        <div className="overflow-hidden rounded border border-gray-200">
          <table className="w-full table-fixed border-collapse text-left text-sm">
            <thead className="bg-gray-50 text-[11px] font-bold uppercase tracking-widest text-gray-500">
              <tr>
                <th className="w-[34%] px-4 py-3">Project</th>
                <th className="w-[14%] px-4 py-3">Updated</th>
                <th className="w-[12%] px-4 py-3">Messages</th>
                <th className="w-[12%] px-4 py-3">Cost</th>
                <th className="w-[16%] px-4 py-3">Feedback</th>
                <th className="w-[12%] px-4 py-3">Trace</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-gray-500">
                    Loading sessions
                  </td>
                </tr>
              ) : sessions.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-gray-500">
                    No matching sessions
                  </td>
                </tr>
              ) : (
                sessions.map((session) => (
                  <tr key={session.id} className="border-t border-gray-100 hover:bg-gray-50">
                    <td className="px-4 py-3">
                      <Link
                        href={`/admin/sessions/${encodeURIComponent(session.id)}`}
                        className="block truncate font-medium text-gray-950 hover:text-[#4a6659]"
                        title={session.project_name}
                      >
                        {session.project_name}
                      </Link>
                      <p className="mt-1 truncate font-mono text-xs text-gray-400">
                        {session.id}
                      </p>
                    </td>
                    <td className="px-4 py-3 text-gray-600">
                      {formatDate(session.updated_at)}
                    </td>
                    <td className="px-4 py-3 text-gray-600">
                      {session.message_count}
                    </td>
                    <td className="px-4 py-3 text-gray-600">
                      {formatCost(session.cost_usd)}
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`rounded border px-2 py-1 text-xs font-semibold ${
                          session.dominant_feedback === "thumbs_down"
                            ? "border-red-200 bg-red-50 text-red-700"
                            : session.dominant_feedback === "thumbs_up"
                              ? "border-green-200 bg-green-50 text-green-700"
                              : "border-gray-200 bg-white text-gray-600"
                        }`}
                      >
                        {session.dominant_feedback.replaceAll("_", " ")}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      {session.cloud_trace_url ? (
                        <a
                          href={session.cloud_trace_url}
                          target="_blank"
                          rel="noreferrer"
                          className="text-sm font-medium text-[#4a6659] hover:underline"
                        >
                          Open
                        </a>
                      ) : (
                        <span className="text-gray-400">None</span>
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>
    </main>
  );
}
