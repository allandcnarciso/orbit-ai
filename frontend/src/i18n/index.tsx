import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import type { ReactNode } from "react";

import { enUS } from "./en-US";
import { esES } from "./es-ES";
import { ptBR } from "./pt-BR";
import type { MessageKey, Messages } from "./pt-BR";

export const LOCALES = ["pt-BR", "en-US", "es-ES"] as const;
export type Locale = (typeof LOCALES)[number];

const STORAGE_KEY = "orbit.locale";
const DEFAULT_LOCALE: Locale = "pt-BR";

const catalogs: Record<Locale, Messages> = {
  "pt-BR": ptBR,
  "en-US": enUS,
  "es-ES": esES,
};

export const localeLabels: Record<Locale, MessageKey> = {
  "pt-BR": "language.ptBR",
  "en-US": "language.enUS",
  "es-ES": "language.esES",
};

function isLocale(value: string | null): value is Locale {
  return value !== null && (LOCALES as readonly string[]).includes(value);
}

function readStoredLocale(): Locale {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    return isLocale(stored) ? stored : DEFAULT_LOCALE;
  } catch {
    return DEFAULT_LOCALE;
  }
}

export type Translate = (
  key: MessageKey,
  variables?: Record<string, string | number>,
) => string;

type I18nContextValue = {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: Translate;
};

const I18nContext = createContext<I18nContextValue | null>(null);

function interpolate(
  template: string,
  variables?: Record<string, string | number>,
): string {
  if (!variables) {
    return template;
  }
  return template.replace(/\{(\w+)\}/g, (match, name: string) => {
    const value = variables[name];
    return value === undefined ? match : String(value);
  });
}

type I18nProviderProps = {
  children: ReactNode;
  initialLocale?: Locale;
};

export function I18nProvider({ children, initialLocale }: I18nProviderProps) {
  const [locale, setLocaleState] = useState<Locale>(
    () => initialLocale ?? readStoredLocale(),
  );

  useEffect(() => {
    document.documentElement.lang = locale;
    try {
      window.localStorage.setItem(STORAGE_KEY, locale);
    } catch {
      // Storage can be unavailable (private mode); the UI still works.
    }
  }, [locale]);

  const setLocale = useCallback((next: Locale) => {
    setLocaleState(next);
  }, []);

  const t = useCallback<Translate>(
    (key, variables) => interpolate(catalogs[locale][key], variables),
    [locale],
  );

  const value = useMemo<I18nContextValue>(
    () => ({ locale, setLocale, t }),
    [locale, setLocale, t],
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nContextValue {
  const context = useContext(I18nContext);
  if (context === null) {
    throw new Error("useI18n must be used inside I18nProvider");
  }
  return context;
}

export type { MessageKey, Messages };
export { catalogs };