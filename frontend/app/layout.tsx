import type { Metadata } from "next";
import Providers from "./providers";
import "./globals.css";

export const metadata: Metadata = {
  title: "RS Generator” Discovery Agent",
  description: "AI-powered Requirement Specification Generator",
  icons: {
    icon: "/skoda.png",
    shortcut: "/skoda.png",
    apple: "/skoda.png",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="cs">
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
