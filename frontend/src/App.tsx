import { Suspense, lazy } from "react";
import { Routes, Route, Navigate } from "react-router-dom";
import { ProtectedRoute } from "./auth/ProtectedRoute";
import { Navbar } from "./components/Navbar";
import { GlobalErrorBoundary } from "./components/GlobalErrorBoundary";
const LoginPage = lazy(() => import("./auth/LoginPage").then((module) => ({ default: module.LoginPage })));
const RegisterPage = lazy(() => import("./auth/RegisterPage").then((module) => ({ default: module.RegisterPage })));
const ForgotPasswordPage = lazy(() => import("./auth/ForgotPasswordPage").then((module) => ({ default: module.ForgotPasswordPage })));
const ProfilePage = lazy(() => import("./profile/ProfilePage").then((module) => ({ default: module.ProfilePage })));
const ResetPasswordByPasswordPage = lazy(() => import("./profile/ResetPasswordByPasswordPage").then((module) => ({ default: module.ResetPasswordByPasswordPage })));
const ResetPasswordByEmailPage = lazy(() => import("./profile/ResetPasswordByEmailPage").then((module) => ({ default: module.ResetPasswordByEmailPage })));
const ChatPage = lazy(() => import("./chat/ChatPage").then((module) => ({ default: module.ChatPage })));
const MyNotebooksPage = lazy(() => import("./notebook/MyNotebooksPage").then((module) => ({ default: module.MyNotebooksPage })));
const NotebookWorkspacePage = lazy(() => import("./workspace/NotebookWorkspacePage").then((module) => ({ default: module.NotebookWorkspacePage })));
const LearningHubPage = lazy(() => import("./zones/LearningHubPage").then((module) => ({ default: module.LearningHubPage })));
const ZoneDetailPage = lazy(() => import("./zones/ZoneDetailPage").then((module) => ({ default: module.ZoneDetailPage })));
const ZoneNotebookWorkspacePage = lazy(() => import("./workspace/ZoneNotebookWorkspacePage").then((module) => ({ default: module.ZoneNotebookWorkspacePage })));
const AdminDashboardPage = lazy(() => import("./admin/AdminDashboardPage").then((module) => ({ default: module.AdminDashboardPage })));
const HealthPage = lazy(() => import("./health/HealthPage").then((module) => ({ default: module.HealthPage })));

const routeLoadingFallback = (
  <div className="p-8 text-center text-gray-500 animate-pulse">
    Loading module...
  </div>
);

export default function App() {
  return (
    <div className="h-screen flex flex-col overflow-hidden bg-gray-100">
      <Navbar />
      <main className="flex-1 min-h-0 overflow-hidden">
        <GlobalErrorBoundary>
          <Suspense fallback={routeLoadingFallback}>
            <Routes>
              <Route path="/login" element={<LoginPage />} />
              <Route path="/register" element={<RegisterPage />} />
              <Route path="/forgot-password" element={<ForgotPasswordPage />} />
              <Route path="/chat" element={<ProtectedRoute><ChatPage /></ProtectedRoute>} />
              <Route path="/profile" element={<ProtectedRoute><ProfilePage /></ProtectedRoute>} />
              <Route path="/profile/reset-password/password" element={<ProtectedRoute><ResetPasswordByPasswordPage /></ProtectedRoute>} />
              <Route path="/profile/reset-password/email" element={<ProtectedRoute><ResetPasswordByEmailPage /></ProtectedRoute>} />
              <Route path="/my-notebooks" element={<ProtectedRoute><MyNotebooksPage /></ProtectedRoute>} />
              <Route path="/notebook/:notebookId" element={<ProtectedRoute><NotebookWorkspacePage /></ProtectedRoute>} />
              <Route path="/learning-hub" element={<ProtectedRoute><LearningHubPage /></ProtectedRoute>} />
              <Route path="/zones/:zoneId" element={<ProtectedRoute><ZoneDetailPage /></ProtectedRoute>} />
              <Route path="/zone-notebook/:zoneId/:notebookId" element={<ProtectedRoute><ZoneNotebookWorkspacePage /></ProtectedRoute>} />
              <Route path="/admin" element={<ProtectedRoute><AdminDashboardPage /></ProtectedRoute>} />
              <Route path="/system-health" element={<ProtectedRoute><HealthPage /></ProtectedRoute>} />
              <Route path="/" element={<Navigate to="/chat" replace />} />
            </Routes>
          </Suspense>
        </GlobalErrorBoundary>
      </main>
    </div>
  );
}
