import { useEffect, useRef } from "react";

import { Icon } from "../Icon";
import { useI18n } from "../../i18n";

type ComposerProps = {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  onStop: () => void;
  generating: boolean;
  modelLabel?: string | null;
};

export const COMPOSER_MAX_LENGTH = 32_000;

export function Composer({
  value,
  onChange,
  onSend,
  onStop,
  generating,
  modelLabel,
}: ComposerProps) {
  const { t } = useI18n();
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const node = textareaRef.current;
    if (node === null) {
      return;
    }
    node.style.height = "auto";
    node.style.height = `${Math.min(node.scrollHeight, 180)}px`;
  }, [value]);

  const canSend = value.trim().length > 0 && !generating;

  return (
    <div className="composer-wrap">
      <div className="composer">
        <label className="visually-hidden" htmlFor="orbit-composer">
          {t("chat.composerPlaceholder")}
        </label>
        <textarea
          id="orbit-composer"
          ref={textareaRef}
          rows={1}
          value={value}
          maxLength={COMPOSER_MAX_LENGTH}
          placeholder={t("chat.composerPlaceholder")}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={(event) => {
            if (
              event.key === "Enter" &&
              !event.shiftKey &&
              !event.nativeEvent.isComposing
            ) {
              event.preventDefault();
              if (canSend) {
                onSend();
              }
            }
          }}
          aria-label={t("chat.composerPlaceholder")}
          aria-describedby="orbit-composer-hint orbit-composer-count"
        />
        {generating ? (
          <button type="button" className="button button--ghost" onClick={onStop}>
            {t("chat.stop")}
          </button>
        ) : (
          <button
            type="button"
            className="button button--primary button--icon"
            aria-label={t("chat.send")}
            title={t("chat.send")}
            disabled={!canSend}
            onClick={onSend}
          >
            <Icon name="send" size={16} />
          </button>
        )}
      </div>
      <div className="composer__hint" id="orbit-composer-hint">
        <span>{t("chat.composerHint")}</span>
        {modelLabel ? <span>{modelLabel}</span> : null}
        <span
          id="orbit-composer-count"
          className={
            value.length >= COMPOSER_MAX_LENGTH * 0.8
              ? "composer__count"
              : "visually-hidden"
          }
        >
          {t("chat.charCount", {
            count: value.length,
            max: COMPOSER_MAX_LENGTH,
          })}
        </span>
      </div>
    </div>
  );
}