import { appendAttachment } from "../app/hooks/useRsState";

describe("appendAttachment", () => {
	it("keeps earlier uploads when a new file is attached", () => {
		expect(appendAttachment("a.xlsx", "b.pdf")).toBe("a.xlsx\nb.pdf");
	});

	it("does not list the same file twice", () => {
		expect(appendAttachment("a.xlsx\nb.pdf", "a.xlsx")).toBe("a.xlsx\nb.pdf");
	});

	it("starts a list from an empty field", () => {
		expect(appendAttachment("", "a.xlsx")).toBe("a.xlsx");
	});
});
