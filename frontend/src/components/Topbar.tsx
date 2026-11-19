import type { RefObject } from "react";

import { useI18n, LOCALES, localeLabels } from "../i18n";
import type { Locale } from "../i18n";
import { Icon } from "./Icon";
import { useTheme } from "../theme/ThemeProvider";

type TopbarProps = {
  title: string;
  onToggleSidebar: () => void;
  expanded: boolean;
  controls: string;
  buttonRef: RefObject<HTMLButtonElement>;
};

export function Topbar({
  title,
  onToggleSidebar,
  expanded,
  controls,
  buttonRef,
}: TopbarProps) {
  const { t, locale, setLocale } = useI18n();
  const { theme, toggleTheme } = useTheme();

  return (
    <header className="topbar">
      <div className="topbar__left">
        <button
          ref={buttonRef}
          type="button"
          className="icon-button"
          onClick={onToggleSidebar}
          aria-label={t("topbar.toggleSidebar")}
          aria-expanded={expanded}
          aria-controls={controls}
          title={t("topbar.toggleSidebar")}
        >
          <Icon name="menu" />
        </button>

        <div className="topbar__heading">
          <span className="topbar__title">{title}</span>
          <span className="topbar__tagline">{t("app.tagline")}</span>
        </div>
      </div>

      <div className="topbar__spacer" />

      <div className="topbar__actions">
        <label className="visually-hidden" htmlFor="orbit-locale">
          {t("topbar.language")}
        </label>
        <Icon name="globe" size={16} aria-hidden="true" />
        <select
          id="orbit-locale"
          className="select"
          value={locale}
          onChange={(event) => setLocale(event.target.value as Locale)}
          aria-label={t("topbar.language")}
        >
          {LOCALES.map((value) => (
            <option key={value} value={value}>
              {t(localeLabels[value])}
            </option>
          ))}
        </select>

        <button
          type="button"
          className="icon-button"
          onClick={toggleTheme}
          aria-label={t("topbar.theme")}
          aria-pressed={theme === "dark"}
          title={
            theme === "dark" ? t("topbar.themeLight") : t("topbar.themeDark")
          }
        >
          <Icon name={theme === "dark" ? "moon" : "sun"} />
        </button>
      </div>
    </header>
  );
}
