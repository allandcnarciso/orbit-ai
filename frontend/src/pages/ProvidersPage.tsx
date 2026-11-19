import { useState } from "react";

import { api } from "../api/client";
import { describeError, describeErrorCode } from "../api/describeError";
import { ApiError } from "../api/errors";
import type { ConnectionTestResponse, ProviderStatus } from "../api/types";
import { useApiResource } from "../api/useApiResource";
import { EmptyBlock, ErrorNotice, LoadingState } from "../components/StateViews";
import { Icon } from "../components/Icon";
import { useI18n } from "../i18n";
import type { MessageKey } from "../i18n";

const capabilityKeys: Array<[keyof ProviderStatus["capabilities"], MessageKey]> = [
  ["streaming", "providers.streaming"],
  ["tools", "providers.tools"],
  ["vision", "providers.vision"],
  ["json_mode", "providers.jsonMode"],
];

function inferProviderErrorCode(detail: string | null): string | null {
  if (detail === null) {
    return null;
  }
  const normalized = detail.toLowerCase();
  if (
    normalized.includes("reach") ||
    normalized.includes("connect") ||
    normalized.includes("unavailable")
  ) {
    return "provider_unavailable";
  }
  if (normalized.includes("timeout") || normalized.includes("timed out")) {
    return "provider_timeout";
  }
  if (
    normalized.includes("401") ||
    normalized.includes("unauthorized") ||
    normalized.includes("api key")
  ) {
    return "provider_auth_error";
  }
  if (normalized.includes("429") || normalized.includes("rate limit")) {
    return "provider_rate_limited";
  }
  return null;
}

function ProviderCard({ provider }: { provider: ProviderStatus }) {
  const { t } = useI18n();
  const [testing, setTesting] = useState(false);
  const [result, setResult] = useState<ConnectionTestResponse | null>(null);
  const [error, setError] = useState<unknown>(null);

  const runTest = async () => {
    setTesting(true);
    setError(null);
    setResult(null);
    try {
      setResult(await api.testProvider(provider.id));
    } catch (testError) {
      setError(testError);
    } finally {
      setTesting(false);
    }
  };

  const requestId = error instanceof ApiError ? error.requestId : null;
  const failureCode =
    result?.code ?? inferProviderErrorCode(result?.detail ?? null);
  const failureMessage = describeErrorCode(failureCode, t);
  const knownFailure =
    failureCode !== null && failureMessage !== t("errors.requestFailed");

  return (
    <article className="card provider-card">
      <header className="provider-card__header">
        <div className="provider-card__identity">
          <div className="provider-card__icon">
            <Icon name="providers" size={18} />
          </div>
          <div>
            <h2>{provider.name}</h2>
            <code className="provider-card__id">{provider.id}</code>
          </div>
        </div>
        <span
          className={`badge ${provider.configured ? "badge--accent" : "badge--warning"}`}
        >
          {provider.configured
            ? t("common.configured")
            : t("common.notConfigured")}
        </span>
      </header>

      {!provider.configured ? (
        <p className="provider-card__hint">{t("providers.requiresConfig")}</p>
      ) : null}

      <div className="provider-card__capabilities">
        <span className="provider-card__label">
          {t("providers.capabilities")}
        </span>
        <div className="chip-row">
          {capabilityKeys.map(([key, labelKey]) => (
            <span
              key={key}
              className={`badge${provider.capabilities[key] ? "" : " badge--off"}`}
            >
              {t(labelKey)}
            </span>
          ))}
        </div>
      </div>

      <div className="provider-card__footer">
        <button
          type="button"
          className="button button--ghost"
          onClick={runTest}
          disabled={testing}
        >
          {testing ? t("common.testing") : t("common.testConnection")}
        </button>

        {result ? (
          <span
            className={`status-text ${result.ok ? "status-text--ok" : "status-text--error"}`}
            role="status"
          >
            {result.ok ? t("providers.testOk") : t("providers.testFailed")}
            {result.ok
              ? ` · ${t("providers.latency", { ms: Math.round(result.latency_ms) })}`
              : null}
            {result.model_count !== null
              ? ` · ${t("providers.modelCount", { count: result.model_count })}`
              : null}
          </span>
        ) : null}
      </div>

      {result && !result.ok ? (
        <p className="provider-card__detail" role="alert">
          {knownFailure ? failureMessage : t("providers.testFailedDetail")}
        </p>
      ) : null}

      {error ? (
        <ErrorNotice
          message={describeError(error, t)}
          requestId={requestId}
        />
      ) : null}
    </article>
  );
}

export function ProvidersPage() {
  const { t } = useI18n();
  const { state, reload } = useApiResource(api.listProviders);

  return (
    <div className="page">
      <header className="page__header">
        <span className="page__eyebrow">ORBIT AI</span>
        <div className="page__title">
          <h1>{t("page.providers.title")}</h1>
          <button
            type="button"
            className="button button--ghost"
            onClick={reload}
            disabled={state.status === "loading"}
          >
            {t("common.refresh")}
          </button>
        </div>
        <p className="page__description">{t("page.providers.description")}</p>
      </header>

      {state.status === "loading" ? <LoadingState /> : null}

      {state.status === "error" ? (
        <ErrorNotice
          message={describeError(state.error, t)}
          requestId={
            state.error instanceof ApiError ? state.error.requestId : null
          }
          onRetry={reload}
        />
      ) : null}

      {state.status === "success" ? (
        state.data.length === 0 ? (
          <EmptyBlock
            title={t("providers.empty")}
            description={t("providers.emptyDescription")}
          />
        ) : (
          <>
            <p className="page__description">{t("providers.configHint")}</p>
            <div className="provider-grid">
              {state.data.map((provider) => (
                <ProviderCard key={provider.id} provider={provider} />
              ))}
            </div>
          </>
        )
      ) : null}
    </div>
  );
}