import { Routes, Route, Navigate } from "react-router-dom";
import { LoginPage } from "./auth/LoginPage";
import { RegisterPage } from "./auth/RegisterPage";
import { ProtectedRoute } from "./auth/ProtectedRoute";
import { ProfilePage } from "./profile/ProfilePage";
import { ChangePasswordPage } from "./profile/ChangePasswordPage";
import { ChatPage } from "./chat/ChatPage";
import { Navbar } from "./components/Navbar";
import { MyNotebooksPage } from "./notebook/MyNotebooksPage";
import { NotebookWorkspacePage } from "./workspace/NotebookWorkspacePage";
import { LearningHubPage } from "./zones/LearningHubPage";
import { ZoneDetailPage } from "./zones/ZoneDetailPage";
import { ZoneNotebookWorkspacePage } from "./workspace/ZoneNotebookWorkspacePage";
import { AdminDashboardPage } from "./admin/AdminDashboardPage";
import { HealthPage } from "./health/HealthPage";

export default function App() {
  return (
    <div className="h-screen flex flex-col overflow-hidden bg-gray-100">
      <Navbar />
      <main className="flex-1 min-h-0 overflow-hidden">
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
          <Route
            path="/chat"
            element={
              <ProtectedRoute>
                <ChatPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/profile"
            element={
              <ProtectedRoute>
                <ProfilePage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/change-password"
            element={
              <ProtectedRoute>
                <ChangePasswordPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/my-notebooks"
            element={
              <ProtectedRoute>
                <MyNotebooksPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/notebook/:notebookId"
            element={
              <ProtectedRoute>
                <NotebookWorkspacePage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/learning-hub"
            element={
              <ProtectedRoute>
                <LearningHubPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/zones/:zoneId"
            element={
              <ProtectedRoute>
                <ZoneDetailPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/zone-notebook/:zoneId/:notebookId"
            element={
              <ProtectedRoute>
                <ZoneNotebookWorkspacePage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/admin"
            element={
              <ProtectedRoute>
                <AdminDashboardPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/health"
            element={
              <ProtectedRoute>
                <HealthPage />
              </ProtectedRoute>
            }
          />
          <Route path="/" element={<Navigate to="/chat" replace />} />
        </Routes>
      </main>
    </div>
  );
}
