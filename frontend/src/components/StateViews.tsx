import type { ReactNode } from "react";

import { useI18n } from "../i18n";

export function LoadingState({ label }: { label?: string }) {
  const { t } = useI18n();
  return (
    <div className="state-block" role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      <span>{label ?? t("common.loading")}</span>
    </div>
  );
}

export function ErrorNotice({
  message,
  requestId,
  onRetry,
}: {
  message: string;
  requestId?: string | null | undefined;
  onRetry?: (() => void) | undefined;
}) {
  const { t } = useI18n();
  return (
    <div className="notice notice--error" role="alert">
      <div className="notice__body">
        <p>{message}</p>
        {requestId ? (
          <p className="notice__meta">
            {t("common.requestId")}: <code>{requestId}</code>
          </p>
        ) : null}
      </div>
      {onRetry ? (
        <button type="button" className="button button--ghost" onClick={onRetry}>
          {t("common.retry")}
        </button>
      ) : null}
    </div>
  );
}

export function WarningNotice({ children }: { children: ReactNode }) {
  return (
    <div className="notice notice--warning" role="status">
      <div className="notice__body">{children}</div>
    </div>
  );
}

export function EmptyBlock({
  title,
  description,
}: {
  title: string;
  description?: string;
}) {
  return (
    <div className="empty-state">
      <h2>{title}</h2>
      {description ? <p>{description}</p> : null}
    </div>
  );
}