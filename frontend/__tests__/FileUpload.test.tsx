import { act, fireEvent, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

import FileUpload from "../app/components/FileUpload";
import { LocaleProvider } from "../app/i18n/LocaleContext";
import { uploadFile } from "../lib/api";

jest.mock("../lib/api", () => ({ uploadFile: jest.fn() }));
const mockUploadFile = uploadFile as jest.MockedFunction<typeof uploadFile>;

function renderUpload() {
	const onUploaded = jest.fn();
	const onError = jest.fn();
	localStorage.setItem("locale", "en");
	const { container } = render(
		<LocaleProvider>
			<FileUpload sessionId="s1" onUploaded={onUploaded} onError={onError} />
		</LocaleProvider>,
	);
	const input = container.querySelector(
		'input[type="file"]',
	) as HTMLInputElement;
	const pick = (...names: string[]) =>
		act(async () => {
			fireEvent.change(input, {
				target: { files: names.map((n) => new File(["x"], n)) },
			});
		});
	return { input, pick, onUploaded, onError };
}

describe("FileUpload", () => {
	beforeEach(() => {
		mockUploadFile.mockReset();
		mockUploadFile.mockImplementation(async (file) => ({
			filename: file.name,
			gcs_path: `uploads/s1/${file.name}`,
		}));
	});

	it("accepts several files at once", () => {
		const { input } = renderUpload();
		expect(input).toHaveAttribute("multiple");
	});

	it("lists every uploaded file and offers to add more", async () => {
		const { pick, onUploaded } = renderUpload();
		expect(screen.queryByText("Add more files")).toBeNull();

		await pick("a.xlsx", "b.pdf");

		expect(screen.getByText("a.xlsx")).toBeInTheDocument();
		expect(screen.getByText("b.pdf")).toBeInTheDocument();
		expect(onUploaded).toHaveBeenCalledTimes(2);
		expect(screen.queryByText(/Drop files or/)).toBeNull();
		expect(
			screen.getByRole("button", { name: /Add more files/ }),
		).toBeInTheDocument();

		await pick("c.docx");
		expect(screen.getByText("c.docx")).toBeInTheDocument();
	});

	it("keeps uploading the rest when one file fails", async () => {
		mockUploadFile.mockImplementation(async (file) => {
			if (file.name === "bad.pdf") throw new Error("Error 500");
			return { filename: file.name, gcs_path: `uploads/s1/${file.name}` };
		});
		const { pick, onError } = renderUpload();

		await pick("bad.pdf", "good.xlsx");

		expect(onError).toHaveBeenCalledWith("bad.pdf: Error 500");
		expect(screen.getByText("good.xlsx")).toBeInTheDocument();
		expect(screen.queryByText("bad.pdf")).toBeNull();
	});
});
