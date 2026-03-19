"use client";

import { useEffect, useRef, useState } from "react";
import { generateBpmn } from "../../lib/api";

// ─── Mermaid renderer ─────────────────────────────────────────────────────────

function MermaidDiagram({ chart }: { chart: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function render() {
      if (!ref.current || !chart) return;
      try {
        const mermaid = (await import("mermaid")).default;
        mermaid.initialize({
          startOnLoad: false,
          theme: "neutral",
          flowchart: { curve: "basis", padding: 20 },
        });

        const id = `mermaid-${Math.random().toString(36).slice(2)}`;
        const { svg } = await mermaid.render(id, chart);
        if (!cancelled && ref.current) {
          ref.current.innerHTML = svg;
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Render error");
        }
      }
    }

    setError(null);
    render();
    return () => { cancelled = true; };
  }, [chart]);

  if (error) {
    return (
      <div className="rounded border border-red-200 bg-[#fff5f5] p-4 text-sm text-red-700">
        <p className="mb-1 font-semibold">Diagram render error</p>
        <pre className="whitespace-pre-wrap text-xs">{error}</pre>
      </div>
    );
  }

  return <div ref={ref} className="w-full overflow-auto" />;
}

// ─── Completeness gate modal ───────────────────────────────────────────────────

function InsufficientDataModal({
  score,
  missing,
  onClose,
}: {
  score: number;
  missing: string[];
  onClose: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="w-full max-w-md rounded-lg border border-gray-200 bg-white p-6 shadow-xl">
        {/* Header */}
        <div className="mb-4 flex items-start justify-between gap-3">
          <div className="flex items-center gap-2">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-amber-100">
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                <path
                  d="M8 2a6 6 0 100 12A6 6 0 008 2zm0 3.5v3m0 2.5h.01"
                  stroke="#d97706"
                  strokeWidth="1.5"
                  strokeLinecap="round"
                />
              </svg>
            </div>
            <h2 className="text-sm font-bold text-gray-900">Not enough information yet</h2>
          </div>
          <button
            onClick={onClose}
            className="shrink-0 rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
          >
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
              <path d="M2 2l10 10M12 2L2 12" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
            </svg>
          </button>
        </div>

        {/* Progress bar */}
        <div className="mb-4">
          <div className="mb-1 flex justify-between text-xs text-gray-500">
            <span>Completeness</span>
            <span className="font-semibold text-gray-700">{score}% / 90% required</span>
          </div>
          <div className="h-2 w-full overflow-hidden rounded-full bg-gray-100">
            <div
              className="h-2 rounded-full bg-amber-400 transition-all duration-500"
              style={{ width: `${score}%` }}
            />
          </div>
        </div>

        {/* Missing items */}
        {missing.length > 0 && (
          <div className="mb-5">
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
              Still needed
            </p>
            <ul className="space-y-1.5">
              {missing.map((item, i) => (
                <li key={i} className="flex items-start gap-2 text-sm text-gray-700">
                  <svg
                    className="mt-0.5 shrink-0 text-amber-400"
                    width="14"
                    height="14"
                    viewBox="0 0 14 14"
                    fill="none"
                  >
                    <circle cx="7" cy="7" r="6" stroke="currentColor" strokeWidth="1.5" />
                    <path d="M7 4.5v3M7 9.5h.01" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                  </svg>
                  {item}
                </li>
              ))}
            </ul>
          </div>
        )}

        <p className="mb-4 text-xs text-gray-500">
          Continue the conversation with the consultant to fill in the missing areas,
          then try generating the diagram again.
        </p>

        <button
          onClick={onClose}
          className="w-full rounded bg-[#4a6659] px-4 py-2 text-sm font-semibold text-white hover:opacity-90"
        >
          Got it — continue the conversation
        </button>
      </div>
    </div>
  );
}

// ─── BPMN Panel ───────────────────────────────────────────────────────────────

export default function BpmnPanel({ sessionId }: { sessionId: string | null }) {
  const [mermaidChart, setMermaidChart] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [apiError, setApiError] = useState<string | null>(null);
  const [gateModal, setGateModal] = useState<{
    score: number;
    missing: string[];
  } | null>(null);

  async function handleGenerate() {
    if (!sessionId) {
      setApiError("Start a conversation first to generate a diagram.");
      return;
    }

    setLoading(true);
    setApiError(null);

    try {
      const result = await generateBpmn(sessionId);

      if (!result.ready) {
        setGateModal({ score: result.score ?? 0, missing: result.missing ?? [] });
        return;
      }

      if (result.mermaid) {
        setMermaidChart(result.mermaid);
      }
    } catch (err) {
      setApiError(err instanceof Error ? err.message : "Failed to generate diagram");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex h-full flex-col">
      {/* Toolbar */}
      <div className="flex shrink-0 items-center justify-between border-b border-gray-100 bg-white px-5 py-3">
        <div>
          <p className="text-sm font-semibold text-gray-800">BPMN Process Diagram</p>
          <p className="text-xs text-gray-400">AI-generated from your requirements conversation</p>
        </div>
        <button
          onClick={handleGenerate}
          disabled={loading}
          className="flex items-center gap-2 rounded bg-[#4a6659] px-4 py-2 text-sm font-semibold text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {loading ? (
            <>
              <svg className="animate-spin" width="14" height="14" viewBox="0 0 24 24" fill="none">
                <circle cx="12" cy="12" r="10" stroke="white" strokeWidth="3" strokeDasharray="31.4" strokeDashoffset="10" />
              </svg>
              Generating…
            </>
          ) : (
            <>
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                <rect x="1" y="4" width="4" height="3" rx="0.5" stroke="white" strokeWidth="1.3" />
                <rect x="9" y="1" width="4" height="3" rx="0.5" stroke="white" strokeWidth="1.3" />
                <rect x="9" y="8" width="4" height="3" rx="0.5" stroke="white" strokeWidth="1.3" />
                <path d="M5 5.5h2.5V2.5H9M5 5.5h2.5v4H9" stroke="white" strokeWidth="1.3" strokeLinecap="round" />
              </svg>
              Generate Diagram
            </>
          )}
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto bg-gray-50 p-5">
        {apiError && (
          <div className="mb-4 rounded border border-red-200 bg-[#fff5f5] px-4 py-3 text-sm text-red-700">
            {apiError}
          </div>
        )}

        {mermaidChart ? (
          <div className="rounded border border-gray-200 bg-white p-4 shadow-sm">
            <MermaidDiagram chart={mermaidChart} />
          </div>
        ) : (
          !apiError && (
            <div className="flex h-full flex-col items-center justify-center gap-3 text-center">
              <div className="flex h-12 w-12 items-center justify-center rounded-full border-2 border-dashed border-gray-300">
                <svg width="20" height="20" viewBox="0 0 20 20" fill="none" className="text-gray-400">
                  <rect x="1" y="6" width="5" height="4" rx="1" stroke="currentColor" strokeWidth="1.4" />
                  <rect x="14" y="2" width="5" height="4" rx="1" stroke="currentColor" strokeWidth="1.4" />
                  <rect x="14" y="12" width="5" height="4" rx="1" stroke="currentColor" strokeWidth="1.4" />
                  <path d="M6 8h4.5V4H14M6 8h4.5v6H14" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
                </svg>
              </div>
              <p className="text-sm font-medium text-gray-500">No diagram yet</p>
              <p className="max-w-xs text-xs text-gray-400">
                Complete at least 90% of the requirements conversation,
                then click <span className="font-medium text-gray-500">Generate Diagram</span>.
              </p>
            </div>
          )
        )}
      </div>

      {/* Insufficient data modal */}
      {gateModal && (
        <InsufficientDataModal
          score={gateModal.score}
          missing={gateModal.missing}
          onClose={() => setGateModal(null)}
        />
      )}
    </div>
  );
}
