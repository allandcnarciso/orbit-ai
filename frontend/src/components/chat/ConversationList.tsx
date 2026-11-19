import { useState } from "react";

import type { Conversation } from "../../api/types";
import { describeError } from "../../api/describeError";
import { useI18n } from "../../i18n";
import type { Locale } from "../../i18n";
import { Icon } from "../Icon";
import { ErrorNotice, LoadingState } from "../StateViews";

type ConversationListProps = {
  conversations: Conversation[];
  total: number;
  selectedId: string | null;
  status: "loading" | "success" | "error";
  error: unknown;
  creating: boolean;
  loadingMore: boolean;
  onCreate: () => void;
  onSelect: (conversationId: string) => void;
  onLoadMore: () => void;
  onRetry: () => void;
};

function formatUpdatedAt(value: string, locale: Locale): string {
  try {
    return new Intl.DateTimeFormat(locale, {
      day: "2-digit",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
    }).format(new Date(value));
  } catch {
    return "";
  }
}

export function ConversationList({
  conversations,
  total,
  selectedId,
  status,
  error,
  creating,
  loadingMore,
  onCreate,
  onSelect,
  onLoadMore,
  onRetry,
}: ConversationListProps) {
  const { t, locale } = useI18n();
  const [search, setSearch] = useState("");

  const needle = search.trim().toLowerCase();
  const filtered = needle
    ? conversations.filter((conversation) =>
        conversation.title.toLowerCase().includes(needle),
      )
    : conversations;

  return (
    <aside className="conversation-sidebar" aria-label={t("chat.conversations")}>
      <div className="conversation-sidebar__header">
        <div className="conversation-sidebar__title">
          <h2>{t("chat.conversations")}</h2>
          {total > 0 ? <span className="badge">{total}</span> : null}
        </div>
        <button
          type="button"
          className="button button--primary"
          onClick={onCreate}
          disabled={creating}
        >
          <Icon name="plus" size={15} />
          {t("chat.newConversation")}
        </button>
      </div>

      <label className="visually-hidden" htmlFor="conversation-search">
        {t("chat.searchConversations")}
      </label>
      <input
        id="conversation-search"
        type="search"
        className="input"
        placeholder={t("chat.searchConversations")}
        value={search}
        onChange={(event) => setSearch(event.target.value)}
      />

      {status === "loading" ? <LoadingState /> : null}

      {status === "error" ? (
        <ErrorNotice message={describeError(error, t)} onRetry={onRetry} />
      ) : null}

      {status === "success" && conversations.length === 0 ? (
        <div className="conversation-sidebar__empty">
          <p>{t("chat.listEmptyTitle")}</p>
          <p>{t("chat.listEmptyDescription")}</p>
        </div>
      ) : null}

      {status === "success" && conversations.length > 0 ? (
        <ul className="conversation-list">
          {filtered.map((conversation) => (
            <li key={conversation.id}>
              <button
                type="button"
                className={`conversation-item${
                  conversation.id === selectedId ? " is-active" : ""
                }`}
                onClick={() => onSelect(conversation.id)}
                aria-current={conversation.id === selectedId ? "true" : undefined}
              >
                <span className="conversation-item__title">
                  {conversation.title}
                </span>
                <span className="conversation-item__meta">
                  {formatUpdatedAt(
                    conversation.last_message_at ?? conversation.updated_at,
                    locale,
                  )}
                </span>
              </button>
            </li>
          ))}
          {filtered.length === 0 ? (
            <li className="conversation-sidebar__empty">
              <p>{t("chat.listEmptyTitle")}</p>
            </li>
          ) : null}
        </ul>
      ) : null}

      {status === "success" && conversations.length < total ? (
        <button
          type="button"
          className="button button--ghost"
          onClick={onLoadMore}
          disabled={loadingMore}
        >
          {loadingMore
            ? t("common.loading")
            : t("chat.loadMoreConversations")}
        </button>
      ) : null}
    </aside>
  );
}