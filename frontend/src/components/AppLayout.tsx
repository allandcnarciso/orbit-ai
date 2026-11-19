import { useCallback, useEffect, useRef, useState } from "react";
import { Outlet, useLocation } from "react-router-dom";

import { useI18n } from "../i18n";
import { DEFAULT_PAGE, PAGE_META } from "../pages/meta";
import { Sidebar } from "./Sidebar";
import { Topbar } from "./Topbar";

const COLLAPSED_KEY = "orbit.sidebar-collapsed";
const SIDEBAR_ID = "orbit-sidebar";

function readCollapsed(): boolean {
  try {
    return window.localStorage.getItem(COLLAPSED_KEY) === "true";
  } catch {
    return false;
  }
}

function mobileQuery(): MediaQueryList | null {
  return typeof window.matchMedia === "function"
    ? window.matchMedia("(max-width: 860px)")
    : null;
}

function isMobileViewport(): boolean {
  return mobileQuery()?.matches ?? false;
}

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function AppLayout() {
  const { t } = useI18n();
  const location = useLocation();
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [isMobile, setIsMobile] = useState(isMobileViewport);
  const menuButtonRef = useRef<HTMLButtonElement>(null);

  const meta = PAGE_META[location.pathname] ?? DEFAULT_PAGE;

  useEffect(() => {
    const query = mobileQuery();
    if (query === null) {
      return;
    }
    const onChange = () => setIsMobile(query.matches);
    setIsMobile(query.matches);
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, []);

  const closeSidebar = useCallback((restoreFocus: boolean) => {
    setMobileOpen(false);
    if (restoreFocus) {
      menuButtonRef.current?.focus();
    }
  }, []);

  useEffect(() => {
    setMobileOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    try {
      window.localStorage.setItem(COLLAPSED_KEY, String(collapsed));
    } catch {
      // Storage unavailable; collapsing still works for this session.
    }
  }, [collapsed]);

  useEffect(() => {
    if (!mobileOpen) {
      return;
    }
    const node = document.getElementById(SIDEBAR_ID);
    const focusable = node
      ? Array.from(node.querySelectorAll<HTMLElement>(FOCUSABLE))
      : [];
    focusable[0]?.focus();

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        closeSidebar(true);
        return;
      }
      if (event.key !== "Tab" || node === null) {
        return;
      }
      const items = Array.from(node.querySelectorAll<HTMLElement>(FOCUSABLE));
      if (items.length === 0) {
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];
      if (first === undefined || last === undefined) {
        return;
      }
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
    };
  }, [mobileOpen, closeSidebar]);

  const toggleSidebar = () => {
    if (isMobile) {
      setMobileOpen((open) => !open);
      return;
    }
    setCollapsed((value) => !value);
  };

  const expanded = isMobile ? mobileOpen : !collapsed;
  const flush = location.pathname === "/chat";

  return (
    <div
      className="app-shell"
      data-collapsed={collapsed}
      data-mobile-open={mobileOpen}
    >
      <a className="skip-link" href="#main-content">
        {t("common.skipToContent")}
      </a>

      <Sidebar
        id={SIDEBAR_ID}
        drawerHidden={isMobile && !mobileOpen}
      />

      {mobileOpen ? (
        <button
          type="button"
          className="mobile-overlay"
          aria-label={t("topbar.closeSidebar")}
          onClick={() => closeSidebar(true)}
        />
      ) : null}

      <div className="app-main">
        <Topbar
          title={t(meta.titleKey)}
          onToggleSidebar={toggleSidebar}
          expanded={expanded}
          controls={SIDEBAR_ID}
          buttonRef={menuButtonRef}
        />
        <main
          id="main-content"
          className={`app-content${flush ? " app-content--flush" : ""}`}
        >
          <Outlet />
        </main>
      </div>
    </div>
  );
}
