import type { MessageKey } from "../i18n";
import type { IconName } from "../components/Icon";

export type PageMeta = {
  titleKey: MessageKey;
  descriptionKey: MessageKey;
  icon: IconName;
};

export const PAGE_META: Record<string, PageMeta> = {
  "/chat": {
    titleKey: "page.chat.title",
    descriptionKey: "page.chat.description",
    icon: "chat",
  },
  "/agents": {
    titleKey: "page.agents.title",
    descriptionKey: "page.agents.description",
    icon: "agents",
  },
  "/models": {
    titleKey: "page.models.title",
    descriptionKey: "page.models.description",
    icon: "models",
  },
  "/providers": {
    titleKey: "page.providers.title",
    descriptionKey: "page.providers.description",
    icon: "providers",
  },
  "/tools": {
    titleKey: "page.tools.title",
    descriptionKey: "page.tools.description",
    icon: "tools",
  },
  "/skills": {
    titleKey: "page.skills.title",
    descriptionKey: "page.skills.description",
    icon: "skills",
  },
  "/memory": {
    titleKey: "page.memory.title",
    descriptionKey: "page.memory.description",
    icon: "memory",
  },
  "/tasks": {
    titleKey: "page.tasks.title",
    descriptionKey: "page.tasks.description",
    icon: "tasks",
  },
  "/settings": {
    titleKey: "page.settings.title",
    descriptionKey: "page.settings.description",
    icon: "settings",
  },
};

export const DEFAULT_PAGE: PageMeta = PAGE_META["/chat"]!;