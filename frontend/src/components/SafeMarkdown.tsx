import ReactMarkdown from "react-markdown";
import type { Components } from "react-markdown";

import { useI18n } from "../i18n";

const ALLOWED_PROTOCOLS = new Set(["http:", "https:", "mailto:"]);

function safeUrl(url: string): string {
  if (url.startsWith("#") || url.startsWith("/")) {
    return url;
  }
  try {
    const parsed = new URL(url);
    return ALLOWED_PROTOCOLS.has(parsed.protocol) ? url : "";
  } catch {
    return "";
  }
}

const baseComponents: Components = {
  a({ href, children }) {
    const safe = href ? safeUrl(href) : "";
    if (!safe) {
      return <span>{children}</span>;
    }
    const external = safe.startsWith("http");
    return (
      <a
        href={safe}
        {...(external
          ? { target: "_blank", rel: "noopener noreferrer nofollow" }
          : {})}
      >
        {children}
      </a>
    );
  },
  code({ className, children }) {
    return <code className={className}>{children}</code>;
  },
};

export function SafeMarkdown({ content }: { content: string }) {
  const { t } = useI18n();
  const components: Components = {
    ...baseComponents,
    img({ alt }) {
      const label = alt ? `${t("chat.imageBlocked")}: ${alt}` : t("chat.imageBlocked");
      return (
        <span className="markdown__image-blocked" role="img" aria-label={label}>
          {label}
        </span>
      );
    },
  };

  return (
    <div className="markdown">
      <ReactMarkdown
        skipHtml
        urlTransform={(url) => safeUrl(url)}
        components={components}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
