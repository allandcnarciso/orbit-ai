import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { AppLayout } from "./components/AppLayout";
import { ComingSoon } from "./components/ComingSoon";
import { I18nProvider } from "./i18n";
import { ChatPage } from "./pages/ChatPage";
import { ModelsPage } from "./pages/ModelsPage";
import { ProvidersPage } from "./pages/ProvidersPage";
import { SettingsPage } from "./pages/SettingsPage";
import { PAGE_META } from "./pages/meta";
import { ThemeProvider } from "./theme/ThemeProvider";

const PLACEHOLDER_ROUTES = [
  "/agents",
  "/tools",
  "/skills",
  "/memory",
  "/tasks",
] as const;

export default function App() {
  return (
    <ThemeProvider>
      <I18nProvider>
        <BrowserRouter>
          <Routes>
            <Route element={<AppLayout />}>
              <Route index element={<Navigate to="/chat" replace />} />
              <Route path="chat" element={<ChatPage />} />
              <Route path="chat/:conversationId" element={<ChatPage />} />
              <Route path="models" element={<ModelsPage />} />
              <Route path="providers" element={<ProvidersPage />} />
              {PLACEHOLDER_ROUTES.map((path) => (
                <Route
                  key={path}
                  path={path.slice(1)}
                  element={<ComingSoon meta={PAGE_META[path]!} />}
                />
              ))}
              <Route path="settings" element={<SettingsPage />} />
              <Route path="*" element={<Navigate to="/chat" replace />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </I18nProvider>
    </ThemeProvider>
  );
}