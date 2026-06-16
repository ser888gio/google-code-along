"use client";

import { SkodaThemeProvider, theme } from "@skodaflow/web-library";
import { LocaleProvider } from "./i18n/LocaleContext";

export default function Providers({ children }: { children: React.ReactNode }) {
	return (
		<LocaleProvider>
			<SkodaThemeProvider theme={theme}>{children}</SkodaThemeProvider>
		</LocaleProvider>
	);
}
