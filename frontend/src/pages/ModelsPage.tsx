import { useMemo, useState } from "react";

import { api } from "../api/client";
import { describeError, describeErrorCode } from "../api/describeError";
import { ApiError } from "../api/errors";
import type {
  AggregatedModelsResponse,
  ModelInfo,
  ModelSelection,
} from "../api/types";
import { useApiResource } from "../api/useApiResource";
import { EmptyBlock, ErrorNotice, LoadingState, WarningNotice } from "../components/StateViews";
import { useI18n } from "../i18n";

type ModelsPageData = {
  catalog: AggregatedModelsResponse;
  defaultSelection: ModelSelection | null;
};

async function loadModelsPage(signal: AbortSignal): Promise<ModelsPageData> {
  const [catalog, defaultSelection] = await Promise.all([
    api.listModels(signal),
    api.getDefaultModel(signal),
  ]);
  return { catalog, defaultSelection };
}

function isDefault(
  model: ModelInfo,
  selection: ModelSelection | null,
): boolean {
  return selection?.provider === model.provider && selection.model === model.id;
}

export function ModelsPage() {
  const { t } = useI18n();
  const { state, reload } = useApiResource(loadModelsPage);
  const [search, setSearch] = useState("");
  const [providerFilter, setProviderFilter] = useState("all");
  const [pendingKey, setPendingKey] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<
    { tone: "success" | "error"; message: string; requestId?: string | null } | null
  >(null);

  const providers = useMemo(() => {
    if (state.status !== "success") {
      return [];
    }
    return [...new Set(state.data.catalog.models.map((model) => model.provider))].sort();
  }, [state]);

  const filteredModels = useMemo(() => {
    if (state.status !== "success") {
      return [];
    }
    const needle = search.trim().toLowerCase();
    return state.data.catalog.models.filter((model) => {
      const matchesProvider =
        providerFilter === "all" || model.provider === providerFilter;
      if (!matchesProvider) {
        return false;
      }
      if (!needle) {
        return true;
      }
      return (
        model.id.toLowerCase().includes(needle) ||
        model.name.toLowerCase().includes(needle)
      );
    });
  }, [state, search, providerFilter]);

  const setDefault = async (model: ModelInfo) => {
    const key = `${model.provider}:${model.id}`;
    setPendingKey(key);
    setFeedback(null);
    try {
      await api.setDefaultModel({ provider: model.provider, model: model.id });
      setFeedback({ tone: "success", message: t("models.defaultSet") });
      reload();
    } catch (error) {
      setFeedback({
        tone: "error",
        message: describeError(error, t),
        requestId: error instanceof ApiError ? error.requestId : null,
      });
    } finally {
      setPendingKey(null);
    }
  };

  const defaultSelection =
    state.status === "success" ? state.data.defaultSelection : null;

  return (
    <div className="page">
      <header className="page__header">
        <span className="page__eyebrow">ORBIT AI</span>
        <div className="page__title">
          <h1>{t("page.models.title")}</h1>
          {state.status === "success" ? (
            <span className="badge">
              {t("models.count", { count: state.data.catalog.models.length })}
            </span>
          ) : null}
          <button
            type="button"
            className="button button--ghost"
            onClick={reload}
            disabled={state.status === "loading"}
          >
            {t("common.refresh")}
          </button>
        </div>
        <p className="page__description">{t("page.models.description")}</p>
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
        <>
          {state.data.catalog.errors.length > 0 ? (
            <WarningNotice>
              <p>{t("models.partialErrors")}</p>
              <ul className="notice__list">
                {state.data.catalog.errors.map((error) => (
                  <li key={`${error.provider}:${error.code}`}>
                    <code>{error.provider}</code> —{" "}
                    {describeErrorCode(error.code, t)}{" "}
                    <span className="notice__code">({error.code})</span>
                  </li>
                ))}
              </ul>
            </WarningNotice>
          ) : null}

          {state.data.catalog.models.length === 0 ? (
            <EmptyBlock
              title={t("models.empty")}
              description={t("models.emptyDescription")}
            />
          ) : (
            <>
              <div className="filters">
                <label className="filters__field">
                  <span className="visually-hidden">
                    {t("models.searchPlaceholder")}
                  </span>
                  <input
                    type="search"
                    className="input"
                    placeholder={t("models.searchPlaceholder")}
                    value={search}
                    onChange={(event) => setSearch(event.target.value)}
                  />
                </label>
                <label className="filters__field">
                  <span className="visually-hidden">
                    {t("models.filterProvider")}
                  </span>
                  <select
                    className="select"
                    aria-label={t("models.filterProvider")}
                    value={providerFilter}
                    onChange={(event) => setProviderFilter(event.target.value)}
                  >
                    <option value="all">{t("models.allProviders")}</option>
                    {providers.map((provider) => (
                      <option key={provider} value={provider}>
                        {provider}
                      </option>
                    ))}
                  </select>
                </label>
              </div>

              {feedback ? (
                feedback.tone === "success" ? (
                  <div className="notice notice--success" role="status">
                    <p>{feedback.message}</p>
                  </div>
                ) : (
                  <ErrorNotice
                    message={feedback.message}
                    requestId={feedback.requestId}
                  />
                )
              ) : null}

              {filteredModels.length === 0 ? (
                <EmptyBlock title={t("models.empty")} />
              ) : (
                <ul className="model-list">
                  {filteredModels.map((model) => {
                    const selected = isDefault(model, defaultSelection);
                    const key = `${model.provider}:${model.id}`;
                    return (
                      <li key={key} className="model-row">
                        <div className="model-row__main">
                          <div className="model-list__title">
                            <span className="model-list__name">{model.name}</span>
                            <code className="model-list__id">{model.id}</code>
                          </div>
                          <div className="chip-row">
                            <span className="badge">{model.provider}</span>
                            {model.context_length !== null ? (
                              <span className="badge badge--off">
                                {t("models.contextLength", {
                                  tokens: model.context_length.toLocaleString(),
                                })}
                              </span>
                            ) : null}
                            {selected ? (
                              <span className="badge badge--accent">
                                {t("models.defaultBadge")}
                              </span>
                            ) : null}
                          </div>
                        </div>

                        {selected ? null : (
                          <button
                            type="button"
                            className="button button--ghost"
                            onClick={() => void setDefault(model)}
                            disabled={pendingKey !== null}
                          >
                            {pendingKey === key
                              ? t("models.settingDefault")
                              : t("models.setDefault")}
                          </button>
                        )}
                      </li>
                    );
                  })}
                </ul>
              )}
            </>
          )}
        </>
      ) : null}
    </div>
  );
}