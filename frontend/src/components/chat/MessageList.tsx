import { useEffect, useRef, useState } from "react";

import type { Message } from "../../api/types";
import { describeErrorCode } from "../../api/describeError";
import { useI18n } from "../../i18n";
import { Icon } from "../Icon";
import { SafeMarkdown } from "../SafeMarkdown";
import type { LiveTurn } from "./types";

type MessageListProps = {
  messages: Message[];
  live: LiveTurn | null;
  hasMore: boolean;
  loadingOlder: boolean;
  onLoadOlder: () => void;
};

type BubbleProps = {
  role: "user" | "assistant";
  content: string;
  status: "streaming" | "cancelling" | "completed" | "failed" | "cancelled";
  provider?: string | null;
  model?: string | null;
  errorCode?: string | null;
  totalTokens?: number | null;
};

function MessageBubble({
  role,
  content,
  status,
  provider,
  model,
  errorCode,
  totalTokens,
}: BubbleProps) {
  const { t } = useI18n();
  const label = role === "user" ? t("chat.you") : t("chat.assistant");

  return (
    <article className={`message message--${role}`}>
      <header className="message__header">
        <span className="message__author">{label}</span>
        {role === "assistant" && provider && model ? (
          <span className="message__model">
            {t("chat.providerModel", { provider, model })}
          </span>
        ) : null}
      </header>

      <div className="message__body">
        {role === "assistant" ? (
          <SafeMarkdown content={content} />
        ) : (
          <p className="message__text">{content}</p>
        )}
      </div>

      {status === "streaming" ? (
        <div className="message__status" role="status">
          <span className="spinner spinner--small" aria-hidden="true" />
          {t("chat.statusStreaming")}
        </div>
      ) : null}

      {status === "cancelling" ? (
        <div className="message__status" role="status">
          <span className="spinner spinner--small" aria-hidden="true" />
          {t("chat.cancelling")}
        </div>
      ) : null}

      {status === "failed" ? (
        <p className="message__status message__status--error" role="alert">
          {t("chat.statusFailed")}
          {errorCode ? ` · ${describeErrorCode(errorCode, t)}` : ""}
        </p>
      ) : null}

      {status === "cancelled" ? (
        <p className="message__status message__status--warning">
          {t("chat.statusCancelled")}
          {content ? ` · ${t("chat.partialResponse")}` : ""}
        </p>
      ) : null}

      {status === "completed" && totalTokens ? (
        <p className="message__meta">
          {t("chat.messageTokens", { count: totalTokens.toLocaleString() })}
        </p>
      ) : null}
    </article>
  );
}

export function MessageList({
  messages,
  live,
  hasMore,
  loadingOlder,
  onLoadOlder,
}: MessageListProps) {
  const { t } = useI18n();
  const containerRef = useRef<HTMLDivElement>(null);
  const [pinned, setPinned] = useState(true);

  useEffect(() => {
    if (!pinned) {
      return;
    }
    const node = containerRef.current;
    if (node !== null) {
      node.scrollTop = node.scrollHeight;
    }
  }, [messages.length, live?.assistantContent.length, live?.status, pinned]);

  const handleScroll = () => {
    const node = containerRef.current;
    if (node === null) {
      return;
    }
    const distance = node.scrollHeight - node.scrollTop - node.clientHeight;
    setPinned(distance < 120);
  };

  const scrollToLatest = () => {
    const node = containerRef.current;
    if (node !== null) {
      node.scrollTop = node.scrollHeight;
    }
    setPinned(true);
  };

  const empty = messages.length === 0 && live === null;

  return (
    <div className="message-area">
      <div
        className="message-scroll"
        id="message-scroll"
        ref={containerRef}
        role="region"
        aria-label={t("chat.messagesLabel")}
        onScroll={handleScroll}
      >
        {hasMore ? (
          <button
            type="button"
            className="button button--ghost message-load-older"
            onClick={onLoadOlder}
            disabled={loadingOlder}
          >
            {loadingOlder ? t("common.loading") : t("chat.loadOlder")}
          </button>
        ) : null}

        {empty ? (
          <div className="empty-state chat-welcome">
            <span className="empty-state__mark">
              <Icon name="chat" size={24} />
            </span>
            <h2>{t("chat.welcomeTitle")}</h2>
            <p>{t("chat.messagesEmpty")}</p>
          </div>
        ) : null}

        {messages.map((message) => (
          <MessageBubble
            key={message.id}
            role={message.role === "user" ? "user" : "assistant"}
            content={message.content}
            status={
              message.status === "failed"
                ? "failed"
                : message.status === "cancelled"
                  ? "cancelled"
                  : message.status === "streaming" ||
                      message.status === "pending"
                    ? "streaming"
                    : "completed"
            }
            provider={message.provider}
            model={message.model}
            errorCode={message.error_code}
            totalTokens={message.total_tokens}
          />
        ))}

        {live !== null ? (
          <>
            <MessageBubble
              role="user"
              content={live.userContent}
              status="completed"
            />
            <MessageBubble
              role="assistant"
              content={live.assistantContent}
              status={live.status}
              provider={live.provider}
              model={live.model}
              errorCode={live.errorCode}
            />
          </>
        ) : null}
      </div>

      {!pinned ? (
        <button
          type="button"
          className="button button--ghost chat-jump"
          onClick={scrollToLatest}
        >
          {t("chat.jumpToLatest")}
        </button>
      ) : null}
    </div>
  );
}