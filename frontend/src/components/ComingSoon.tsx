import { useI18n } from "../i18n";
import type { PageMeta } from "../pages/meta";
import { Icon } from "./Icon";

export function ComingSoon({ meta }: { meta: PageMeta }) {
  const { t } = useI18n();

  return (
    <div className="page">
      <header className="page__header">
        <span className="page__eyebrow">ORBIT AI</span>
        <div className="page__title">
          <h1>{t(meta.titleKey)}</h1>
          <span className="badge badge--accent">{t("common.comingSoon")}</span>
        </div>
        <p className="page__description">{t(meta.descriptionKey)}</p>
      </header>

      <div className="coming-soon">
        <div className="coming-soon__icon">
          <Icon name={meta.icon} size={20} />
        </div>
        <div className="coming-soon__body">
          <h2>{t("common.comingSoon")}</h2>
          <p>{t("common.comingSoonDescription")}</p>
        </div>
      </div>
    </div>
  );
}