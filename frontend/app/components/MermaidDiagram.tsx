"use client";

import { useEffect, useRef, useState } from "react";

export default function MermaidDiagram({
  chart,
  idPrefix,
}: {
  chart: string;
  idPrefix: string;
}) {
  const ref = useRef<HTMLIFrameElement>(null);
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
          securityLevel: "strict",
          flowchart: { curve: "basis", padding: 20 },
        });

        const id = `${idPrefix}-${crypto.randomUUID()}`;
        const { svg } = await mermaid.render(id, chart);
        if (!cancelled && ref.current) {
          ref.current.srcdoc = `<!doctype html><html><body style="margin:0">${svg}</body></html>`;
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Render error");
        }
      }
    }

    setError(null);
    render();
    return () => {
      cancelled = true;
    };
  }, [chart, idPrefix]);

  if (error) {
    return (
      <div className="rounded border border-red-200 bg-[#fff5f5] p-4 text-sm text-red-700">
        <p className="mb-1 font-semibold">Diagram render error</p>
        <pre className="whitespace-pre-wrap text-xs">{error}</pre>
      </div>
    );
  }

  return (
    <iframe
      ref={ref}
      sandbox=""
      title="Generated Mermaid diagram"
      className="h-140 w-full border-0"
    />
  );
}
