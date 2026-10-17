"use client";

import { useLocale } from "./LocaleContext";

export default function LanguageSwitcher() {
	const { locale, setLocale } = useLocale();

	return (
		<div className="flex items-center rounded border border-gray-200 text-xs font-semibold overflow-hidden">
			<button
				type="button"
				onClick={() => setLocale("cs")}
				className={`px-2.5 py-2 transition-colors lg:px-2 lg:py-1 ${
					locale === "cs"
						? "bg-[#1a3a2a] text-white"
						: "text-gray-500 hover:bg-gray-100"
				}`}
			>
				CZ
			</button>
			<button
				type="button"
				onClick={() => setLocale("en")}
				className={`px-2.5 py-2 transition-colors border-l border-gray-200 lg:px-2 lg:py-1 ${
					locale === "en"
						? "bg-[#1a3a2a] text-white"
						: "text-gray-500 hover:bg-gray-100"
				}`}
			>
				EN
			</button>
		</div>
	);
}
