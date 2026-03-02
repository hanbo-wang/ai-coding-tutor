import {
  createContext,
  useState,
  useEffect,
  ReactNode,
} from "react";
import {
  ChangePasswordData,
  User,
  LoginCredentials,
  RegisterData,
  PasswordResetConfirmData,
  ProfileUpdateData,
} from "../api/types";
import { apiFetch, setAccessToken } from "../api/http";

interface AuthContextType {
  user: User | null;
  isLoading: boolean;
  login: (credentials: LoginCredentials) => Promise<void>;
  sendRegisterCode: (email: string) => Promise<void>;
  register: (data: RegisterData) => Promise<void>;
  logout: () => Promise<void>;
  updateProfile: (data: ProfileUpdateData) => Promise<void>;
  changePassword: (data: ChangePasswordData) => Promise<void>;
  sendPasswordResetCode: (email: string) => Promise<void>;
  resetPassword: (data: PasswordResetConfirmData) => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  // On mount, try to restore session via refresh token
  useEffect(() => {
    async function restoreSession() {
      try {
        const response = await fetch("/api/auth/refresh", {
          method: "POST",
          credentials: "include",
        });
        if (response.ok) {
          const data = await response.json();
          setAccessToken(data.access_token);
          const userProfile = await apiFetch<User>("/api/auth/me");
          setUser(userProfile);
        }
      } catch {
        // Session expired or no refresh token
        setAccessToken(null);
      } finally {
        setIsLoading(false);
      }
    }
    restoreSession();
  }, []);

  const login = async (credentials: LoginCredentials) => {
    const data = await apiFetch<{ access_token: string }>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify(credentials),
    });
    setAccessToken(data.access_token);
    const userProfile = await apiFetch<User>("/api/auth/me");
    setUser(userProfile);
  };

  const sendRegisterCode = async (email: string) => {
    await apiFetch<{ message: string }>("/api/auth/register/send-code", {
      method: "POST",
      body: JSON.stringify({ email }),
    });
  };

  const register = async (registerData: RegisterData) => {
    const data = await apiFetch<{ access_token: string }>("/api/auth/register", {
      method: "POST",
      body: JSON.stringify(registerData),
    });
    setAccessToken(data.access_token);
    const userProfile = await apiFetch<User>("/api/auth/me");
    setUser(userProfile);
  };

  const logout = async () => {
    await fetch("/api/auth/logout", { method: "POST", credentials: "include" });
    setAccessToken(null);
    setUser(null);
  };

  const updateProfile = async (data: ProfileUpdateData) => {
    const updatedUser = await apiFetch<User>("/api/auth/me", {
      method: "PUT",
      body: JSON.stringify(data),
    });
    setUser(updatedUser);
  };

  const changePassword = async (data: ChangePasswordData) => {
    await apiFetch<{ message: string }>("/api/auth/me/password", {
      method: "PUT",
      body: JSON.stringify(data),
    });
  };

  const sendPasswordResetCode = async (email: string) => {
    await apiFetch<{ message: string }>("/api/auth/password-reset/send-code", {
      method: "POST",
      body: JSON.stringify({ email }),
    });
  };

  const resetPassword = async (data: PasswordResetConfirmData) => {
    await apiFetch<{ message: string }>("/api/auth/password-reset/confirm", {
      method: "POST",
      body: JSON.stringify(data),
    });
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        isLoading,
        login,
        sendRegisterCode,
        register,
        logout,
        updateProfile,
        changePassword,
        sendPasswordResetCode,
        resetPassword,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export { AuthContext };
