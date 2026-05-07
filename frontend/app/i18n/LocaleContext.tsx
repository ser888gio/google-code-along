"use client";

import { createContext, useContext, useEffect, useState } from "react";
import cs from "./cs.json";
import en from "./en.json";

type Locale = "cs" | "en";

const translations: Record<Locale, Record<string, string>> = { cs, en };

const LocaleContext = createContext<{
  locale: Locale;
  setLocale: (l: Locale) => void;
  t: (key: string) => string;
}>({
  locale: "cs",
  setLocale: () => {},
  t: (k) => k,
});

export function LocaleProvider({ children }: { children: React.ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>("cs");

  useEffect(() => {
    const saved = localStorage.getItem("locale") as Locale | null;
    if (saved === "en" || saved === "cs") setLocaleState(saved);
  }, []);

  function setLocale(l: Locale) {
    setLocaleState(l);
    localStorage.setItem("locale", l);
  }

  const t = (key: string) => translations[locale][key] ?? key;

  return (
    <LocaleContext.Provider value={{ locale, setLocale, t }}>
      {children}
    </LocaleContext.Provider>
  );
}

export const useLocale = () => useContext(LocaleContext);
