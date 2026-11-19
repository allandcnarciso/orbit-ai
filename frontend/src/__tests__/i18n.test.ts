import { describe, expect, it } from "vitest";

import { LOCALES, catalogs } from "../i18n";

describe("translations", () => {
  const baseKeys = Object.keys(catalogs["pt-BR"]).sort();

  it.each(LOCALES)("locale %s has every message key", (locale) => {
    expect(Object.keys(catalogs[locale]).sort()).toEqual(baseKeys);
  });

  it.each(LOCALES)("locale %s has no empty messages", (locale) => {
    for (const [key, value] of Object.entries(catalogs[locale])) {
      expect(value.trim(), `${locale}:${key}`).not.toHaveLength(0);
    }
  });

  it("keeps the tagline and brand name untranslated", () => {
    for (const locale of LOCALES) {
      expect(catalogs[locale]["app.tagline"]).toContain("One Harness");
    }
  });
});