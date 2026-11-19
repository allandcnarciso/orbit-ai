import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";

function createMatchMedia(matches: boolean) {
  return (query: string): MediaQueryList =>
    ({
      matches,
      media: query,
      onchange: null,
      addListener: () => undefined,
      removeListener: () => undefined,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      dispatchEvent: () => false,
    }) as unknown as MediaQueryList;
}

if (typeof window.matchMedia !== "function") {
  window.matchMedia = createMatchMedia(false);
}

beforeEach(() => {
  window.localStorage.clear();
  document.documentElement.dataset.theme = "dark";
  document.documentElement.lang = "pt-BR";
  window.history.pushState({}, "", "/chat");
  // Fail fast by default; individual tests install explicit route mocks.
  vi.stubGlobal(
    "fetch",
    vi.fn(() => Promise.reject(new TypeError("network disabled in tests"))),
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});