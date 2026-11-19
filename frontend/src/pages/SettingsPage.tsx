import { API_BASE, APP_VERSION, DOCS_URL } from "../config";
import { api } from "../api/client";
import { describeError } from "../api/describeError";
import { ApiError } from "../api/errors";
import { useApiResource } from "../api/useApiResource";
import { ErrorNotice, LoadingState } from "../components/StateViews";
import { useI18n, LOCALES, localeLabels } from "../i18n";
import type { Locale } from "../i18n";
import { useTheme } from "../theme/ThemeProvider";
import { Icon } from "../components/Icon";

function formatStartedAt(value: string, locale: Locale): string {
  try {
    return new Intl.DateTimeFormat(locale, {
      dateStyle: "medium",
      timeStyle: "short",
    }).format(new Date(value));
  } catch {
    return value;
  }
}

function requestIdOf(error: unknown): string | null {
  return error instanceof ApiError ? error.requestId : null;
}

export function SettingsPage() {
  const { t, locale, setLocale } = useI18n();
  const { theme, setTheme } = useTheme();
  const health = useApiResource(api.health);
  const system = useApiResource(api.systemInfo);

  return (
    <div className="page">
      <header className="page__header">
        <span className="page__eyebrow">ORBIT AI</span>
        <div className="page__title">
          <h1>{t("page.settings.title")}</h1>
        </div>
        <p className="page__description">{t("page.settings.description")}</p>
      </header>

      <section className="card settings-grid" aria-labelledby="settings-appearance">
        <h2 id="settings-appearance">{t("settings.appearance")}</h2>

        <div className="settings-row">
          <div className="settings-row__text">
            <span className="settings-row__label">{t("settings.theme")}</span>
            <span className="settings-row__description">
              {t("settings.themeDescription")}
            </span>
          </div>
          <div className="segmented" role="group" aria-label={t("settings.theme")}>
            <button
              type="button"
              aria-pressed={theme === "light"}
              onClick={() => setTheme("light")}
            >
              <Icon name="sun" size={15} />
              {t("settings.light")}
            </button>
            <button
              type="button"
              aria-pressed={theme === "dark"}
              onClick={() => setTheme("dark")}
            >
              <Icon name="moon" size={15} />
              {t("settings.dark")}
            </button>
          </div>
        </div>

        <div className="settings-row">
          <div className="settings-row__text">
            <span className="settings-row__label">
              {t("settings.language")}
            </span>
            <span className="settings-row__description">
              {t("settings.languageDescription")}
            </span>
          </div>
          <label className="visually-hidden" htmlFor="settings-locale">
            {t("settings.language")}
          </label>
          <select
            id="settings-locale"
            className="select"
            value={locale}
            onChange={(event) => setLocale(event.target.value as Locale)}
          >
            {LOCALES.map((value) => (
              <option key={value} value={value}>
                {t(localeLabels[value])}
              </option>
            ))}
          </select>
        </div>
      </section>

      <section className="card settings-grid" aria-labelledby="settings-about">
        <h2 id="settings-about">{t("settings.about")}</h2>

        <dl className="kv">
          <dt>{t("settings.version")}</dt>
          <dd>v{APP_VERSION}</dd>
          <dt>{t("settings.apiBase")}</dt>
          <dd>{API_BASE}</dd>
          <dt>{t("settings.docs")}</dt>
          <dd>
            <a href={DOCS_URL} target="_blank" rel="noreferrer">
              {DOCS_URL}
            </a>
          </dd>
        </dl>

        <p className="settings-row__description">
          {t("settings.apiBaseDescription")}
        </p>
      </section>

      <section className="card settings-grid" aria-labelledby="settings-health">
        <div className="section-heading">
          <h2 id="settings-health">{t("settings.health")}</h2>
          <button
            type="button"
            className="button button--ghost"
            onClick={health.reload}
            disabled={health.state.status === "loading"}
          >
            {t("common.refresh")}
          </button>
        </div>

        {health.state.status === "loading" ? <LoadingState /> : null}

        {health.state.status === "error" ? (
          <ErrorNotice
            message={describeError(health.state.error, t)}
            requestId={requestIdOf(health.state.error)}
            onRetry={health.reload}
          />
        ) : null}

        {health.state.status === "success" ? (
          <>
            <div className="settings-row">
              <span className="settings-row__label">
                {t("settings.healthStatus")}
              </span>
              <span
                className={`badge ${
                  health.state.data.status === "ok"
                    ? "badge--success"
                    : "badge--warning"
                }`}
              >
                {health.state.data.status === "ok"
                  ? t("settings.healthOperational")
                  : t("settings.healthUnavailable")}
              </span>
            </div>
            <dl className="kv">
              {Object.entries(health.state.data.checks).map(([name, value]) => (
                <div key={name} className="kv__row">
                  <dt>{name}</dt>
                  <dd>{value}</dd>
                </div>
              ))}
            </dl>
          </>
        ) : null}
      </section>

      <section className="card settings-grid" aria-labelledby="settings-system">
        <div className="section-heading">
          <h2 id="settings-system">{t("settings.system")}</h2>
          <button
            type="button"
            className="button button--ghost"
            onClick={system.reload}
            disabled={system.state.status === "loading"}
          >
            {t("common.refresh")}
          </button>
        </div>

        {system.state.status === "loading" ? <LoadingState /> : null}

        {system.state.status === "error" ? (
          <ErrorNotice
            message={describeError(system.state.error, t)}
            requestId={requestIdOf(system.state.error)}
            onRetry={system.reload}
          />
        ) : null}

        {system.state.status === "success" ? (
          <dl className="kv">
            <dt>{t("settings.apiVersion")}</dt>
            <dd>{system.state.data.api_version}</dd>
            <dt>{t("settings.environment")}</dt>
            <dd>{system.state.data.environment}</dd>
            <dt>{t("settings.python")}</dt>
            <dd>{system.state.data.python}</dd>
            <dt>{t("settings.platform")}</dt>
            <dd>{system.state.data.platform}</dd>
            <dt>{t("settings.architecture")}</dt>
            <dd>{system.state.data.architecture}</dd>
            <dt>{t("settings.startedAt")}</dt>
            <dd>{formatStartedAt(system.state.data.started_at, locale)}</dd>
          </dl>
        ) : null}
      </section>

      <section className="card card--muted">
        <p className="settings-row__description">{t("settings.backendNote")}</p>
      </section>
    </div>
  );
}