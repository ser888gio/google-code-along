"use client";

import { StyledEngineProvider } from "@mui/material/styles";
import { SkodaThemeProvider, theme } from "@skodaflow/web-library";
import { LocaleProvider } from "./i18n/LocaleContext";

export default function Providers({ children }: { children: React.ReactNode }) {
	return (
		<LocaleProvider>
			{/* enableCssLayer wraps MUI's unlayered baseline (h1–h4 sizes etc.) in
			    `@layer mui`, so Tailwind utilities are no longer overridden. */}
			<StyledEngineProvider enableCssLayer>
				<SkodaThemeProvider theme={theme}>{children}</SkodaThemeProvider>
			</StyledEngineProvider>
		</LocaleProvider>
	);
}
