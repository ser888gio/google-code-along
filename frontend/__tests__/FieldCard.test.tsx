import { fireEvent, render, screen } from "@testing-library/react";
import type React from "react";
import "@testing-library/jest-dom";

import FieldCard from "../app/components/FieldCard";
import { LocaleProvider } from "../app/i18n/LocaleContext";
import type { FieldSource, RsField } from "../lib/api";

function field(overrides: Partial<RsField> = {}): RsField {
	return { value: "v", filled: true, source: null, updatedAt: 0, ...overrides };
}

function renderCard(
	props: Partial<React.ComponentProps<typeof FieldCard>> = {},
) {
	const handlers = {
		onChange: jest.fn(),
		onAcceptSuggestion: jest.fn(),
		onDismissSuggestion: jest.fn(),
	};
	localStorage.setItem("locale", "en");
	const { container } = render(
		<LocaleProvider>
			<FieldCard
				label="Owner"
				fieldKey="product_owner"
				field={undefined}
				{...handlers}
				{...props}
			/>
		</LocaleProvider>,
	);
	return {
		...handlers,
		card: container.querySelector("div.rounded") as HTMLElement,
	};
}

describe("FieldCard", () => {
	it.each([
		["user_manual", "User"],
		["user_direct_chat", "Chat"],
		["user_accept_suggestion", "Accepted AI"],
		["user_upload", "Upload"],
	] as const)("shows the %s badge as %s when filled", (source, label) => {
		renderCard({ field: field({ source: source as FieldSource }) });
		expect(screen.getByText(label)).toBeInTheDocument();
	});

	it("shows no badge for AI-sourced or unfilled fields", () => {
		renderCard({ field: field({ source: "ai" as FieldSource }) });
		for (const label of ["User", "Chat", "Accepted AI", "Upload"]) {
			expect(screen.queryByText(label)).toBeNull();
		}
	});

	it("shows no badge when the field is not filled", () => {
		renderCard({ field: field({ filled: false, source: "user_manual" }) });
		expect(screen.queryByText("User")).toBeNull();
	});

	it.each([
		[
			"suggestion",
			{ field: field({ pendingSuggestion: { value: "x", receivedAt: 0 } }) },
			"border-yellow-300",
		],
		["filled", { field: field() }, "border-gray-200"],
		["extracting", { isExtracting: true }, "animate-shimmer"],
		["empty", {}, "border-dashed"],
	] as const)("uses the %s border", (_name, props, cls) => {
		const { card } = renderCard(props);
		expect(card.className).toContain(cls);
	});

	it("does not shimmer an empty field when not extracting", () => {
		const { card } = renderCard();
		expect(card.className).not.toContain("animate-shimmer");
	});

	it("rings recently changed fields", () => {
		const { card } = renderCard({ isRecentlyChanged: true });
		expect(card.className).toContain("ring-green-400");
	});

	it("keeps the ring until the field has been visible for a moment", () => {
		jest.useFakeTimers();
		let report: IntersectionObserverCallback = () => {};
		global.IntersectionObserver = jest.fn(
			(cb: IntersectionObserverCallback) => {
				report = cb;
				return { observe: jest.fn(), disconnect: jest.fn() };
			},
		) as unknown as typeof IntersectionObserver;
		const seen = (isIntersecting: boolean) =>
			report(
				[{ isIntersecting } as IntersectionObserverEntry],
				{} as IntersectionObserver,
			);
		const onViewed = jest.fn();
		renderCard({ isRecentlyChanged: true, onViewed });

		seen(true);
		jest.advanceTimersByTime(1000);
		seen(false);
		jest.advanceTimersByTime(5000);
		expect(onViewed).not.toHaveBeenCalled();

		seen(true);
		jest.advanceTimersByTime(2500);
		expect(onViewed).toHaveBeenCalledTimes(1);
		jest.useRealTimers();
	});

	it.each([
		[true, 3],
		[false, 1],
	])(
		"renders multiline=%s as a textarea starting at %i row(s)",
		(multiline, rows) => {
			renderCard({ multiline });
			const box = screen.getByRole("textbox");
			expect(box.tagName).toBe("TEXTAREA");
			expect(box).toHaveAttribute("rows", String(rows));
		},
	);

	it("shows the placeholder only while unfilled and reports edits", () => {
		const { onChange } = renderCard();
		const box = screen.getByPlaceholderText("Gathering…");
		fireEvent.change(box, { target: { value: "Ales" } });
		expect(onChange).toHaveBeenCalledWith("product_owner", "Ales");
	});

	it("keeps single-line fields free of line breaks", () => {
		const { onChange } = renderCard();
		fireEvent.change(screen.getByRole("textbox"), {
			target: { value: "Ales\nNovak" },
		});
		expect(onChange).toHaveBeenCalledWith("product_owner", "Ales Novak");
	});

	it("keeps line breaks in multiline fields", () => {
		const { onChange } = renderCard({ multiline: true });
		fireEvent.change(screen.getByRole("textbox"), {
			target: { value: "a\nb" },
		});
		expect(onChange).toHaveBeenCalledWith("product_owner", "a\nb");
	});

	it("routes accept and dismiss for a pending suggestion", () => {
		const { onAcceptSuggestion, onDismissSuggestion } = renderCard({
			field: field({ pendingSuggestion: { value: "Jana", receivedAt: 0 } }),
		});
		expect(screen.getByText("AI suggests: Jana")).toBeInTheDocument();
		fireEvent.click(screen.getByRole("button", { name: "Accept" }));
		fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
		expect(onAcceptSuggestion).toHaveBeenCalledWith("product_owner");
		expect(onDismissSuggestion).toHaveBeenCalledWith("product_owner");
	});
});
