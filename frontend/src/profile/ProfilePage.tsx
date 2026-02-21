import { useState, useEffect, FormEvent } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../auth/useAuth";
import { apiFetch } from "../api/http";
import { TokenUsage } from "../api/types";

export function ProfilePage() {
  const { user, updateProfile } = useAuth();
  const [username, setUsername] = useState(user?.username ?? "");
  const [programmingLevel, setProgrammingLevel] = useState(
    user?.programming_level ?? 3
  );
  const [mathsLevel, setMathsLevel] = useState(user?.maths_level ?? 3);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [message, setMessage] = useState("");

  const [usage, setUsage] = useState<TokenUsage | null>(null);

  useEffect(() => {
    apiFetch<TokenUsage>("/api/chat/usage")
      .then(setUsage)
      .catch((err) => console.error("Failed to fetch usage:", err));
  }, []);

  const handleProfileSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setIsSubmitting(true);
    setMessage("");

    try {
      await updateProfile({
        username,
        programming_level: programmingLevel,
        maths_level: mathsLevel,
      });
      setMessage("Profile updated successfully!");
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Update failed");
    } finally {
      setIsSubmitting(false);
    }
  };

  if (!user) {
    return null;
  }

  const levelLabels = ["Beginner", "Elementary", "Intermediate", "Advanced", "Expert"];

  return (
    <div className="h-full overflow-y-auto">
    <div className="max-w-lg mx-auto py-8 px-4 space-y-6">
      {/* Profile info */}
      <div className="bg-white rounded-lg shadow-md p-8">
        <h1 className="text-2xl font-bold text-center text-brand mb-6">Profile</h1>

        {message && (
          <div
            className={`px-4 py-3 rounded mb-4 ${
              message.includes("success")
                ? "bg-green-100 border border-green-400 text-green-700"
                : "bg-red-100 border border-red-400 text-red-700"
            }`}
          >
            {message}
          </div>
        )}

        <div className="space-y-2 mb-6">
          <div>
            <span className="text-sm font-medium text-gray-700">Email:</span>
            <p className="text-gray-900">{user.email}</p>
          </div>
          <div className="flex items-center justify-between">
            <div>
              <span className="text-sm font-medium text-gray-700">Password:</span>
              <p className="text-gray-900">********</p>
            </div>
            <Link
              to="/change-password"
              className="text-sm text-accent-dark hover:underline"
            >
              Change Password
            </Link>
          </div>
          <div>
            <span className="text-sm font-medium text-gray-700">
              Member since:
            </span>
            <p className="text-gray-900">
              {new Date(user.created_at).toLocaleDateString()}
            </p>
          </div>
        </div>

        <form onSubmit={handleProfileSubmit} className="space-y-4">
          <div>
            <label
              htmlFor="username"
              className="block text-sm font-medium text-gray-700 mb-1"
            >
              Username
            </label>
            <input
              type="text"
              id="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-accent"
              minLength={3}
              maxLength={50}
              required
            />
          </div>

          <div>
            <label
              htmlFor="programmingLevel"
              className="block text-sm font-medium text-gray-700 mb-1"
            >
              Programming Level: {levelLabels[programmingLevel - 1]}
            </label>
            <input
              type="range"
              id="programmingLevel"
              min="1"
              max="5"
              value={programmingLevel}
              onChange={(e) => setProgrammingLevel(parseInt(e.target.value))}
              className="w-full accent-accent"
            />
            <div className="flex justify-between text-xs text-gray-500">
              <span>Beginner</span>
              <span>Expert</span>
            </div>
          </div>

          <div>
            <label
              htmlFor="mathsLevel"
              className="block text-sm font-medium text-gray-700 mb-1"
            >
              Mathematics Level: {levelLabels[mathsLevel - 1]}
            </label>
            <input
              type="range"
              id="mathsLevel"
              min="1"
              max="5"
              value={mathsLevel}
              onChange={(e) => setMathsLevel(parseInt(e.target.value))}
              className="w-full accent-accent"
            />
            <div className="flex justify-between text-xs text-gray-500">
              <span>Beginner</span>
              <span>Expert</span>
            </div>
          </div>

          <button
            type="submit"
            disabled={isSubmitting}
            className="w-full bg-brand text-white py-2 px-4 rounded-md hover:bg-brand-light focus:outline-none focus:ring-2 focus:ring-accent disabled:opacity-50"
          >
            {isSubmitting ? "Saving..." : "Save Changes"}
          </button>
        </form>
      </div>

      {/* Daily usage */}
      {usage && (
        <div className="bg-white rounded-lg shadow-md p-6">
          <h2 className="text-lg font-bold text-brand mb-3">Daily Usage</h2>
          <div className="w-full bg-gray-200 rounded-full h-4 mb-2">
            <div
              className="bg-accent h-4 rounded-full transition-all"
              style={{ width: `${Math.min(usage.usage_percentage, 100)}%` }}
            />
          </div>
          <p className="text-sm text-gray-600">
            {usage.usage_percentage.toFixed(1)}% of daily limit used
          </p>
        </div>
      )}
    </div>
    </div>
  );
}
