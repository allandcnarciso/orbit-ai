type LogoProps = {
  size?: number;
  withText?: boolean;
  tagline?: string;
};

export function Logo({ size = 28, withText = false, tagline }: LogoProps) {
  return (
    <span className="logo" aria-label="ORBIT AI">
      <svg
        width={size}
        height={size}
        viewBox="0 0 32 32"
        fill="none"
        aria-hidden="true"
        focusable="false"
      >
        <circle cx="16" cy="16" r="4.6" fill="var(--accent)" />
        <ellipse
          cx="16"
          cy="16"
          rx="13"
          ry="6.4"
          stroke="var(--accent)"
          strokeWidth="1.5"
          opacity="0.6"
          transform="rotate(-28 16 16)"
        />
        <circle cx="26.3" cy="10.4" r="1.6" fill="var(--accent)" />
      </svg>
      {withText ? (
        <span className="sidebar__brand-text">
          <span className="sidebar__brand-name">ORBIT AI</span>
          {tagline ? (
            <span className="sidebar__brand-tagline">{tagline}</span>
          ) : null}
        </span>
      ) : null}
    </span>
  );
}
