"use client";

import { SkodaThemeProvider, theme } from "@skodaflow/web-library";

export default function Providers({ children }: { children: React.ReactNode }) {
  return (
    <SkodaThemeProvider theme={theme}>
      {children}
    </SkodaThemeProvider>
  );
}
