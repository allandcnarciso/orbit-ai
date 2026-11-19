import { useEffect, useRef } from "react";
import { NavLink } from "react-router-dom";

import { useI18n } from "../i18n";
import type { MessageKey } from "../i18n";
import { Icon } from "./Icon";
import type { IconName } from "./Icon";
import { Logo } from "./Logo";
import { APP_VERSION } from "../config";

export type NavItem = {
  to: string;
  labelKey: MessageKey;
  icon: IconName;
};

export const NAV_ITEMS: NavItem[] = [
  { to: "/chat", labelKey: "nav.chat", icon: "chat" },
  { to: "/agents", labelKey: "nav.agents", icon: "agents" },
  { to: "/models", labelKey: "nav.models", icon: "models" },
  { to: "/providers", labelKey: "nav.providers", icon: "providers" },
  { to: "/tools", labelKey: "nav.tools", icon: "tools" },
  { to: "/skills", labelKey: "nav.skills", icon: "skills" },
  { to: "/memory", labelKey: "nav.memory", icon: "memory" },
  { to: "/tasks", labelKey: "nav.tasks", icon: "tasks" },
  { to: "/settings", labelKey: "nav.settings", icon: "settings" },
];

type SidebarProps = {
  id: string;
  drawerHidden: boolean;
};

export function Sidebar({ id, drawerHidden }: SidebarProps) {
  const { t } = useI18n();
  const ref = useRef<HTMLElement>(null);

  useEffect(() => {
    const node = ref.current;
    if (node !== null) {
      node.inert = drawerHidden;
    }
  }, [drawerHidden]);

  return (
    <aside
      id={id}
      ref={ref}
      className="sidebar"
      aria-label={t("nav.primary")}
      aria-hidden={drawerHidden ? true : undefined}
    >
      <NavLink to="/chat" className="sidebar__brand" aria-label={t("app.home")}>
        <Logo size={26} withText tagline={t("app.tagline")} />
      </NavLink>

      <nav className="sidebar__nav" aria-label={t("nav.primary")}>
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) =>
              `sidebar__link${isActive ? " is-active" : ""}`
            }
            title={t(item.labelKey)}
            aria-label={t(item.labelKey)}
          >
            <span className="sidebar__link-icon" aria-hidden="true">
              <Icon name={item.icon} />
            </span>
            <span className="sidebar__link-label">{t(item.labelKey)}</span>
          </NavLink>
        ))}
      </nav>

      <div className="sidebar__footer">
        {t("app.preAlpha")} · v{APP_VERSION}
      </div>
    </aside>
  );
}