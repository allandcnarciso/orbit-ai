import { useEffect } from "react";
import { useNavigate } from "react-router-dom";

import { describeError } from "../api/describeError";
import { ApiError } from "../api/errors";
import { ConversationList } from "../components/chat/ConversationList";
import { Composer } from "../components/chat/Composer";
import { MessageList } from "../components/chat/MessageList";
import { useChatController } from "../components/chat/useChatController";
import { ErrorNotice, LoadingState } from "../components/StateViews";
import { Icon } from "../components/Icon";
import { useI18n } from "../i18n";

export function ChatPage() {
  const c = useChatController();
  const { t } = useI18n();
  const navigate = useNavigate();

  const title =
    c.selectedConversation?.title ??
    (c.conversationId !== null
      ? t("chat.conversations")
      : t("chat.selectConversationTitle"));

  useEffect(() => {
    const status = c.live?.status;
    if (status === "cancelled" || status === "failed") {
      document.getElementById("orbit-composer")?.focus();
    }
  }, [c.live?.status]);

  return (
    <div className="chat-page" data-active={c.conversationId !== null}>
      <p className="visually-hidden" role="status" aria-live="polite">
        {c.announcement}
      </p>
      <ConversationList
        conversations={c.conversations}
        total={c.total}
        selectedId={c.conversationId}
        status={c.conversationsStatus}
        error={c.conversationsError}
        creating={c.creating}
        loadingMore={c.loadingMore}
        onCreate={() => void c.createConversation()}
        onSelect={c.selectConversation}
        onLoadMore={c.loadMoreConversations}
        onRetry={c.refreshConversations}
      />

      <section className="chat-main" aria-label={t("page.chat.title")}>
        <header className="chat-header">
          <button
            type="button"
            className="icon-button chat-back"
            onClick={() => navigate("/chat", { state: { manual: true } })}
            aria-label={t("chat.backToConversations")}
            title={t("chat.backToConversations")}
          >
            <Icon name="arrow-left" />
          </button>

          <div className="chat-header__info">
            <h1 className="chat-header__title">{title}</h1>
            {c.modelLabel ? (
              <span className="badge chat-header__model">{c.modelLabel}</span>
            ) : null}
          </div>

          {c.sending ? (
            <span className="chat-generating" role="status">
              <span className="spinner spinner--small" aria-hidden="true" />
              {t("chat.generating")}
            </span>
          ) : null}
        </header>

        {c.sendError ? (
          <div className="chat-alert">
            <ErrorNotice
              message={c.sendError}
              onRetry={c.retryVisible ? c.retrySend : undefined}
            />
          </div>
        ) : null}

        {c.messagesStatus === "loading" ? <LoadingState /> : null}

        {c.messagesStatus === "error" ? (
          <div className="chat-alert">
            <ErrorNotice
              message={describeError(c.messagesError, t)}
              requestId={
                c.messagesError instanceof ApiError
                  ? c.messagesError.requestId
                  : null
              }
              onRetry={c.reloadMessages}
            />
          </div>
        ) : null}

        {c.messagesStatus !== "error" ? (
          <MessageList
            messages={c.messages}
            live={c.live}
            hasMore={c.hasMore}
            loadingOlder={c.loadingOlder}
            onLoadOlder={() => void c.loadOlderMessages()}
          />
        ) : null}

        <div className="chat-composer">
          <Composer
            value={c.draft}
            onChange={c.setDraft}
            onSend={() => void c.sendMessage(c.draft)}
            onStop={() => void c.stopGeneration()}
            generating={c.sending}
            modelLabel={c.modelLabel}
          />
        </div>
      </section>
    </div>
  );
}