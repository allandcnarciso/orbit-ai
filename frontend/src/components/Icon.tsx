import type { SVGProps } from "react";

export type IconName =
  | "chat"
  | "agents"
  | "models"
  | "providers"
  | "tools"
  | "skills"
  | "memory"
  | "tasks"
  | "settings"
  | "menu"
  | "close"
  | "sun"
  | "moon"
  | "globe"
  | "arrow-right"
  | "arrow-left"
  | "plus"
  | "send";

const paths: Record<IconName, string[]> = {
  chat: [
    "M21 11.5a8.4 8.4 0 0 1-8.5 8.5 8.9 8.9 0 0 1-3.8-.85L3 21l1.9-5.2A8.4 8.4 0 0 1 12.5 3 8.4 8.4 0 0 1 21 11.5Z",
  ],
  agents: [
    "M12 3v3",
    "M12 18v3",
    "M3 12h3",
    "M18 12h3",
    "M6.3 6.3 8.4 8.4",
    "M15.6 15.6l2.1 2.1",
    "M17.7 6.3 15.6 8.4",
    "M8.4 15.6l-2.1 2.1",
    "M12 8.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7Z",
  ],
  models: [
    "M12 2.8 20 7v10l-8 4.2L4 17V7l8-4.2Z",
    "M4 7l8 4.2L20 7",
    "M12 11.2v10",
  ],
  providers: [
    "M4 5.5h16v5H4z",
    "M4 13.5h16v5H4z",
    "M7.5 8h.01",
    "M7.5 16h.01",
  ],
  tools: [
    "M14.5 6.5a4 4 0 0 1 5 5L11 20l-4 1 1-4 8.5-8.5Z",
    "M6 6l3 3",
  ],
  skills: [
    "M4 5.5A2.5 2.5 0 0 1 6.5 3H20v16H6.5A2.5 2.5 0 0 0 4 21.5V5.5Z",
    "M4 18.5A2.5 2.5 0 0 1 6.5 16H20",
  ],
  memory: [
    "M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3Z",
    "M4 6v6c0 1.7 3.6 3 8 3s8-1.3 8-3V6",
    "M4 12v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6",
  ],
  tasks: [
    "M9 4h6a2 2 0 0 1 2 2v15l-5-3-5 3V6a2 2 0 0 1 2-2Z",
    "M9 9h6",
    "M9 13h4",
  ],
  settings: [
    "M12 15.2a3.2 3.2 0 1 0 0-6.4 3.2 3.2 0 0 0 0 6.4Z",
    "M19.4 15a1.7 1.7 0 0 0 .34 1.87l.06.06-1.42 2.46-.09-.03a1.7 1.7 0 0 0-1.8.22 1.7 1.7 0 0 0-.62 1.73l.03.09h-2.84l.03-.09a1.7 1.7 0 0 0-.62-1.73 1.7 1.7 0 0 0-1.8-.22l-.09.03-1.42-2.46.06-.06A1.7 1.7 0 0 0 9.6 15a1.7 1.7 0 0 0-1.6-1.06H7.9v-2.84l.1-.01A1.7 1.7 0 0 0 9.6 10a1.7 1.7 0 0 0-.34-1.87l-.06-.06 1.42-2.46.09.03a1.7 1.7 0 0 0 1.8-.22 1.7 1.7 0 0 0 .62-1.73L13.1 3.6h2.84l-.03.09a1.7 1.7 0 0 0 .62 1.73 1.7 1.7 0 0 0 1.8.22l.09-.03 1.42 2.46-.06.06A1.7 1.7 0 0 0 19.4 10c.13.6.65 1.06 1.28 1.1l.1.01v2.84l-.1.01A1.7 1.7 0 0 0 19.4 15Z",
  ],
  menu: ["M4 7h16", "M4 12h16", "M4 17h16"],
  close: ["M6 6l12 12", "M18 6 6 18"],
  sun: [
    "M12 16.5a4.5 4.5 0 1 0 0-9 4.5 4.5 0 0 0 0 9Z",
    "M12 2v2",
    "M12 20v2",
    "M4.9 4.9l1.4 1.4",
    "M17.7 17.7l1.4 1.4",
    "M2 12h2",
    "M20 12h2",
    "M4.9 19.1l1.4-1.4",
    "M17.7 6.3l1.4-1.4",
  ],
  moon: ["M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5Z"],
  globe: [
    "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z",
    "M3.5 9h17",
    "M3.5 15h17",
    "M12 3c2.2 2.4 3.3 5.6 3.3 9S14.2 18.6 12 21c-2.2-2.4-3.3-5.6-3.3-9S9.8 5.4 12 3Z",
  ],
  "arrow-right": ["M5 12h14", "M13 6l6 6-6 6"],
  "arrow-left": ["M19 12H5", "M11 6l-6 6 6 6"],
  plus: ["M12 5v14", "M5 12h14"],
  send: ["M21 3 10.5 13.5", "M21 3l-6.5 18-4-7.5L3 9.5 21 3Z"],
};

type IconProps = SVGProps<SVGSVGElement> & {
  name: IconName;
  size?: number;
};

export function Icon({ name, size = 18, ...props }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...props}
    >
      {paths[name].map((d) => (
        <path key={d} d={d} />
      ))}
    </svg>
  );
}