"use client";

import { useEffect, useRef, useState } from "react";

// Below this scale diagram text becomes unreadable, so narrow screens scroll
// horizontally inside the iframe instead of shrinking further.
const MIN_SCALE = 0.8;
const SCROLLBAR_ALLOWANCE = 16;

function naturalSize(svg: string): { w: number; h: number } | null {
	const m = svg.match(/viewBox="[-\d.]+\s+[-\d.]+\s+([\d.]+)\s+([\d.]+)"/);
	if (!m) return null;
	const w = Number.parseFloat(m[1]);
	const h = Number.parseFloat(m[2]);
	return w > 0 && h > 0 ? { w, h } : null;
}

export default function MermaidDiagram({
	chart,
	idPrefix,
}: {
	chart: string;
	idPrefix: string;
}) {
	const ref = useRef<HTMLIFrameElement>(null);
	const [error, setError] = useState<string | null>(null);
	const [size, setSize] = useState<{ w: number; h: number } | null>(null);
	const [boxWidth, setBoxWidth] = useState(0);

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
					const natural = naturalSize(svg);
					const fit = natural
						? `svg{display:block;width:100%;max-width:${natural.w}px;min-width:${Math.round(natural.w * MIN_SCALE)}px;height:auto;margin:0 auto}`
						: "";
					ref.current.srcdoc = `<!doctype html><html><head><style>body{margin:0}${fit}</style></head><body>${svg}</body></html>`;
					setSize(natural);
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

	// Track the available width so the iframe height matches the scaled diagram.
	useEffect(() => {
		const el = ref.current;
		if (!el || typeof ResizeObserver === "undefined") return;
		const observer = new ResizeObserver(() => setBoxWidth(el.clientWidth));
		observer.observe(el);
		return () => observer.disconnect();
	}, []);

	if (error) {
		return (
			<div className="rounded border border-red-200 bg-[#fff5f5] p-4 text-sm text-red-700">
				<p className="mb-1 font-semibold">Diagram render error</p>
				<pre className="whitespace-pre-wrap text-xs">{error}</pre>
			</div>
		);
	}

	let height: number | undefined;
	if (size && boxWidth > 0) {
		const rendered = Math.min(
			size.w,
			Math.max(boxWidth, size.w * MIN_SCALE),
		);
		const scrolls = rendered > boxWidth;
		height =
			Math.ceil((rendered * size.h) / size.w) +
			(scrolls ? SCROLLBAR_ALLOWANCE : 0);
	}

	return (
		<iframe
			ref={ref}
			sandbox=""
			title="Generated Mermaid diagram"
			className={`w-full border-0 ${height ? "" : "h-140"}`}
			style={height ? { height } : undefined}
		/>
	);
}
