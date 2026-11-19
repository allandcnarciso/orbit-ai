import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams, useLocation } from "react-router-dom";

import { api, openMessageStream } from "../../api/client";
import { describeError, localizedErrorForCode } from "../../api/describeError";
import { ApiError } from "../../api/errors";
import { parseSse } from "../../api/sse";
import type {
  ContentDeltaData,
  Conversation,
  Message,
  MessageCancelledData,
  MessageCompletedData,
  MessageFailedData,
  MessageStartedData,
  ModelSelection,
} from "../../api/types";
import type { LiveTurn } from "./types";
import { useI18n } from "../../i18n";

const LIST_LIMIT = 50;
const MESSAGE_LIMIT = 100;

type ConversationsStatus = "loading" | "success" | "error";
type MessagesStatus = "idle" | "loading" | "success" | "error";

type RetryAttempt = {
  content: string;
  clientMessageId: string;
  safe: boolean;
};

const TERMINAL_MESSAGE_STATUSES = new Set([
  "completed",
  "failed",
  "cancelled",
]);

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function createClientMessageId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

function asString(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function deltaText(data: unknown): string {
  if (typeof data === "object" && data !== null && "delta" in data) {
    const delta = (data as { delta?: unknown }).delta;
    return typeof delta === "string" ? delta : "";
  }
  return "";
}

export function useChatController() {
  const { conversationId = null } = useParams<{ conversationId?: string }>();
  const navigate = useNavigate();
  const { t } = useI18n();

  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [total, setTotal] = useState(0);
  const [conversationsStatus, setConversationsStatus] =
    useState<ConversationsStatus>("loading");
  const [conversationsError, setConversationsError] = useState<unknown>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [creating, setCreating] = useState(false);

  const [messages, setMessages] = useState<Message[]>([]);
  const [messagesStatus, setMessagesStatus] = useState<MessagesStatus>("idle");
  const [messagesError, setMessagesError] = useState<unknown>(null);
  const [hasMore, setHasMore] = useState(false);
  const [nextBefore, setNextBefore] = useState<number | null>(null);
  const [loadingOlder, setLoadingOlder] = useState(false);

  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [live, setLive] = useState<LiveTurn | null>(null);
  const [announcement, setAnnouncement] = useState("");
  const announcedRef = useRef("");
  const [sendError, setSendError] = useState<string | null>(null);
  const [retryAttempt, setRetryAttempt] = useState<RetryAttempt | null>(null);
  const [defaultModel, setDefaultModel] = useState<ModelSelection | null>(null);
  const location = useLocation();

  const conversationIdRef = useRef<string | null>(conversationId);
  const activeConversationRef = useRef<string | null>(null);
  const controllerRef = useRef<AbortController | null>(null);
  const sendingRef = useRef(false);
  const assistantIdRef = useRef<string | null>(null);
  const attemptTokenRef = useRef(0);
  const cancelFallbackRef = useRef<number | null>(null);
  const conversationsAbortRef = useRef<AbortController | null>(null);
  const messagesAbortRef = useRef<AbortController | null>(null);
  const autoSelectedRef = useRef(false);

  const loadConversations = useCallback(
    async (offset = 0, append = false, silent = false) => {
      conversationsAbortRef.current?.abort();
      const controller = new AbortController();
      conversationsAbortRef.current = controller;
      if (append) {
        setLoadingMore(true);
      } else if (!silent) {
        setConversationsStatus("loading");
      }

      try {
        const data = await api.listConversations({
          limit: LIST_LIMIT,
          offset,
          signal: controller.signal,
        });
        if (controller.signal.aborted) {
          return;
        }
        setConversations((previous) => {
          if (!append) {
            return data.items;
          }
          const seen = new Set(previous.map((item) => item.id));
          return [...previous, ...data.items.filter((item) => !seen.has(item.id))];
        });
        setTotal(data.total);
        setConversationsStatus("success");
        setConversationsError(null);
      } catch (error) {
        if (!controller.signal.aborted) {
          setConversationsError(error);
          setConversationsStatus("error");
        }
      } finally {
        if (!controller.signal.aborted) {
          setLoadingMore(false);
        }
      }
    },
    [],
  );

  const loadMessages = useCallback(
    async (targetId: string, silent = false): Promise<Message[] | null> => {
      messagesAbortRef.current?.abort();
      const controller = new AbortController();
      messagesAbortRef.current = controller;
      if (!silent) {
        setMessagesStatus("loading");
      }

      try {
        const data = await api.listMessages(targetId, {
          limit: MESSAGE_LIMIT,
          signal: controller.signal,
        });
        if (controller.signal.aborted) {
          return null;
        }
        if (conversationIdRef.current === targetId) {
          setMessages(data.items);
          setHasMore(data.has_more);
          setNextBefore(data.next_before_sequence);
          setMessagesStatus("success");
          setMessagesError(null);
        }
        return data.items;
      } catch (error) {
        if (!controller.signal.aborted) {
          setMessagesError(error);
          if (!silent) {
            setMessagesStatus("error");
          }
        }
        return null;
      }
    },
    [],
  );

  useEffect(() => {
    void loadConversations(0, false);
    return () => conversationsAbortRef.current?.abort();
  }, [loadConversations]);

  useEffect(() => {
    conversationIdRef.current = conversationId;
    if (conversationId === null) {
      setMessages([]);
      setMessagesStatus("idle");
      setHasMore(false);
      setNextBefore(null);
      return;
    }
    void loadMessages(conversationId);
    return () => messagesAbortRef.current?.abort();
  }, [conversationId, loadMessages]);

  useEffect(() => {
    const controller = new AbortController();
    api
      .getDefaultModel(controller.signal)
      .then(setDefaultModel)
      .catch(() => undefined);
    return () => controller.abort();
  }, []);

  const liveConversationId = live?.conversationId;
  const liveStatus = live?.status;

  useEffect(() => {
    if (liveConversationId === undefined || liveStatus === undefined) {
      return;
    }
    if (liveConversationId !== conversationIdRef.current) {
      return;
    }
    const key =
      liveStatus === "streaming"
        ? "chat.announceStarted"
        : liveStatus === "completed"
          ? "chat.announceCompleted"
          : liveStatus === "cancelled"
            ? "chat.announceCancelled"
            : liveStatus === "failed"
              ? "chat.announceFailed"
              : null;
    if (key === null) {
      return;
    }
    const marker = `${liveConversationId}:${liveStatus}`;
    if (announcedRef.current === marker) {
      return;
    }
    announcedRef.current = marker;
    setAnnouncement(t(key));
  }, [liveConversationId, liveStatus, t]);

  useEffect(() => {
    const manualBack =
      (location.state as { manual?: boolean } | null)?.manual === true;
    if (
      conversationId !== null ||
      conversationsStatus !== "success" ||
      conversations.length === 0 ||
      autoSelectedRef.current ||
      manualBack
    ) {
      return;
    }
    autoSelectedRef.current = true;
    navigate(`/chat/${conversations[0]!.id}`, { replace: true });
  }, [
    conversationId,
    conversations,
    conversationsStatus,
    navigate,
    location.state,
  ]);

  const detachActiveStream = useCallback(() => {
    controllerRef.current?.abort();
    controllerRef.current = null;
    activeConversationRef.current = null;
    if (cancelFallbackRef.current !== null) {
      window.clearTimeout(cancelFallbackRef.current);
      cancelFallbackRef.current = null;
    }
    sendingRef.current = false;
    setSending(false);
    setLive(null);
    attemptTokenRef.current += 1;
    assistantIdRef.current = null;
  }, []);

  useEffect(() => {
    const active = activeConversationRef.current;
    if (active !== null && active !== conversationId) {
      detachActiveStream();
    }
  }, [conversationId, detachActiveStream]);

  useEffect(() => {
    return () => {
      controllerRef.current?.abort();
      if (cancelFallbackRef.current !== null) {
        window.clearTimeout(cancelFallbackRef.current);
      }
    };
  }, []);

  const refreshAfterTerminal = async (targetId: string) => {
    const items = await loadMessages(targetId, true);
    void loadConversations(0, false, true);
    if (conversationIdRef.current !== targetId) {
      return;
    }
    if (items !== null) {
      setLive(null);
    } else {
      setSendError(t("chat.historyStale"));
    }
  };

  const reconcileTerminal = async (
    targetId: string,
    token: number,
    attempts = 8,
  ): Promise<boolean> => {
    for (let attempt = 0; attempt < attempts; attempt += 1) {
      if (token !== attemptTokenRef.current) {
        return false;
      }
      const items = await loadMessages(targetId, true);
      if (items !== null && token === attemptTokenRef.current) {
        const assistantId = assistantIdRef.current;
        const confirmed =
          assistantId === null ||
          items.some(
            (message) =>
              message.id === assistantId &&
              TERMINAL_MESSAGE_STATUSES.has(message.status),
          );
        if (confirmed) {
          if (conversationIdRef.current === targetId) {
            setLive(null);
          }
          return true;
        }
      }
      if (conversationIdRef.current !== targetId) {
        return false;
      }
      await delay(250 * (attempt + 1));
    }

    if (
      token === attemptTokenRef.current &&
      conversationIdRef.current === targetId
    ) {
      setLive((previous) =>
        previous === null
          ? previous
          : {
              ...previous,
              status: "failed",
              errorCode: "stream_interrupted",
              errorMessage: t("chat.streamInterrupted"),
            },
      );
      setSendError(t("chat.historyStale"));
    }
    return false;
  };

  const selectConversation = (targetId: string) => {
    if (targetId === conversationId) {
      return;
    }
    if (activeConversationRef.current !== null) {
      detachActiveStream();
    }
    navigate(`/chat/${targetId}`);
  };

  const createConversation = async () => {
    if (creating) {
      return;
    }
    setCreating(true);
    setSendError(null);
    try {
      const created = await api.createConversation({
        title: t("chat.newConversation"),
      });
      setConversations((previous) => [created, ...previous]);
      setTotal((value) => value + 1);
      if (activeConversationRef.current !== null) {
        detachActiveStream();
      }
      navigate(`/chat/${created.id}`);
      setDraft("");
    } catch (error) {
      setSendError(describeError(error, t));
    } finally {
      setCreating(false);
    }
  };

  const refreshConversations = () => {
    void loadConversations(0, false);
  };

  const loadMoreConversations = () => {
    void loadConversations(conversations.length, true);
  };

  const loadOlderMessages = async () => {
    if (conversationId === null || nextBefore === null || loadingOlder) {
      return;
    }
    setLoadingOlder(true);
    try {
      const data = await api.listMessages(conversationId, {
        beforeSequence: nextBefore,
        limit: MESSAGE_LIMIT,
      });
      setMessages((previous) => [...data.items, ...previous]);
      setHasMore(data.has_more);
      setNextBefore(data.next_before_sequence);
    } catch (error) {
      setMessagesError(error);
    } finally {
      setLoadingOlder(false);
    }
  };

  const sendMessage = async (rawContent: string, retry?: RetryAttempt) => {
    const content = rawContent.trim();
    if (content.length === 0 || sendingRef.current) {
      return;
    }
    sendingRef.current = true;

    setSendError(null);
    setRetryAttempt(null);
    const clientMessageId = retry?.clientMessageId ?? createClientMessageId();
    const token = attemptTokenRef.current + 1;
    attemptTokenRef.current = token;
    assistantIdRef.current = null;
    let targetId = conversationId;

    try {
      if (targetId === null) {
        const created = await api.createConversation({
          title: content.slice(0, 60),
        });
        targetId = created.id;
        setConversations((previous) => [created, ...previous]);
        setTotal((value) => value + 1);
        navigate(`/chat/${targetId}`, { replace: true });
      }
    } catch (error) {
      setSendError(describeError(error, t));
      sendingRef.current = false;
      return;
    }

    const controller = new AbortController();
    controllerRef.current = controller;
    activeConversationRef.current = targetId;
    setSending(true);
    setLive({
      conversationId: targetId,
      userContent: content,
      userId: null,
      assistantId: null,
      assistantContent: "",
      provider: null,
      model: null,
      status: "streaming",
      errorCode: null,
      errorMessage: null,
    });
    setDraft("");

    let terminal = false;
    try {
      const response = await openMessageStream(
        targetId,
        {
          content,
          stream: true,
          client_message_id: clientMessageId,
        },
        controller.signal,
      );

      for await (const event of parseSse(response.body as ReadableStream<Uint8Array>)) {
        if (controller.signal.aborted) {
          break;
        }

        if (event.event === "message.started") {
          const data = event.data as MessageStartedData;
          assistantIdRef.current = asString(data.message_id);
          setLive((previous) =>
            previous === null || previous.conversationId !== targetId
              ? previous
              : {
                  ...previous,
                  userId: asString(data.user_message_id),
                  assistantId: asString(data.message_id),
                  provider: asString(data.provider),
                  model: asString(data.model),
                },
          );
        } else if (event.event === "content.delta") {
          const delta = deltaText(event.data as ContentDeltaData);
          if (delta) {
            setLive((previous) =>
              previous === null || previous.conversationId !== targetId
                ? previous
                : {
                    ...previous,
                    assistantContent: previous.assistantContent + delta,
                  },
            );
          }
        } else if (event.event === "message.completed") {
          const data = event.data as MessageCompletedData;
          terminal = true;
          setLive((previous) =>
            previous === null || previous.conversationId !== targetId
              ? previous
              : {
                  ...previous,
                  assistantContent: asString(data.content) ?? previous.assistantContent,
                  status: "completed",
                  provider: asString(data.provider) ?? previous.provider,
                  model: asString(data.model) ?? previous.model,
                },
          );
        } else if (event.event === "message.failed") {
          const data = event.data as MessageFailedData;
          terminal = true;
          const errorCode = asString(data.error?.code);
          setLive((previous) =>
            previous === null || previous.conversationId !== targetId
              ? previous
              : {
                  ...previous,
                  status: "failed",
                  errorCode,
                  errorMessage:
                    localizedErrorForCode(errorCode, t) ??
                    asString(data.error?.message),
                },
          );
        } else if (event.event === "message.cancelled") {
          const data = event.data as MessageCancelledData;
          terminal = true;
          setLive((previous) =>
            previous === null || previous.conversationId !== targetId
              ? previous
              : {
                  ...previous,
                  assistantContent: asString(data.content) ?? previous.assistantContent,
                  status: "cancelled",
                  errorCode: asString(data.reason),
                },
          );
        }

        if (terminal) {
          break;
        }
      }

      if (!terminal && !controller.signal.aborted) {
        setLive((previous) =>
          previous === null || previous.conversationId !== targetId
            ? previous
            : {
                ...previous,
                status: "failed",
                errorCode: "stream_interrupted",
                errorMessage: t("chat.streamInterrupted"),
              },
        );
        setSendError(t("chat.streamInterrupted"));
        void reconcileTerminal(targetId, token);
      }

      if (terminal) {
        await refreshAfterTerminal(targetId);
      }
    } catch (error) {
      if (controller.signal.aborted) {
        return;
      }
      const retryable =
        !(error instanceof ApiError) || error.status >= 500;
      const safe = assistantIdRef.current === null && retryable;
      setLive((previous) =>
        previous === null || previous.conversationId !== targetId
          ? previous
          : {
              ...previous,
              status: "failed",
              errorCode:
                error instanceof ApiError ? error.code : "stream_interrupted",
              errorMessage: t("chat.streamInterrupted"),
            },
      );
      setSendError(describeError(error, t));
      setRetryAttempt({ content, clientMessageId, safe });
      void reconcileTerminal(targetId, token);
    } finally {
      if (cancelFallbackRef.current !== null) {
        window.clearTimeout(cancelFallbackRef.current);
        cancelFallbackRef.current = null;
      }
      if (controllerRef.current === controller) {
        controllerRef.current = null;
        activeConversationRef.current = null;
        sendingRef.current = false;
        setSending(false);
      }
    }
  };

  const retrySend = () => {
    if (retryAttempt === null || !retryAttempt.safe) {
      return;
    }
    void sendMessage(retryAttempt.content, retryAttempt);
  };

  const stopGeneration = async () => {
    const targetId = activeConversationRef.current;
    if (targetId === null) {
      return;
    }
    const token = attemptTokenRef.current;
    setLive((previous) =>
      previous === null || previous.conversationId !== targetId
        ? previous
        : { ...previous, status: "cancelling" },
    );

    try {
      await api.cancelGeneration(targetId);
      cancelFallbackRef.current = window.setTimeout(() => {
        if (activeConversationRef.current === targetId) {
          controllerRef.current?.abort();
        }
        void reconcileTerminal(targetId, token);
      }, 8_000);
    } catch (error) {
      setSendError(t("chat.cancelFailed"));
      controllerRef.current?.abort();
      setLive((previous) =>
        previous === null || previous.conversationId !== targetId
          ? previous
          : {
              ...previous,
              status: "cancelling",
              errorCode: "cancel_failed",
              errorMessage: describeError(error, t),
            },
      );
      void reconcileTerminal(targetId, token);
    }
  };

  const selectedConversation =
    conversations.find((item) => item.id === conversationId) ?? null;
  const modelLabel = selectedConversation?.model
    ? selectedConversation.provider
      ? t("chat.providerModel", {
          provider: selectedConversation.provider,
          model: selectedConversation.model,
        })
      : selectedConversation.model
    : defaultModel
      ? t("chat.headerDefaultModel", {
          model: defaultModel.model,
        })
      : null;

  return {
    conversationId,
    conversations,
    total,
    conversationsStatus,
    conversationsError,
    loadingMore,
    creating,
    messages,
    messagesStatus,
    messagesError,
    hasMore,
    loadingOlder,
    draft,
    setDraft,
    sending,
    live,
    announcement,
    sendError,
    retryAttempt,
    modelLabel,
    selectedConversation,
    selectConversation,
    createConversation,
    refreshConversations,
    loadMoreConversations,
    loadOlderMessages,
    reloadMessages: () => {
      if (conversationId !== null) {
        void loadMessages(conversationId);
      }
    },
    sendMessage,
    retrySend,
    stopGeneration,
    retryVisible: retryAttempt !== null && retryAttempt.safe,
  };
}

export type ChatController = ReturnType<typeof useChatController>;