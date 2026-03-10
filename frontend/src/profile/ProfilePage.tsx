import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiFetch } from "../api/http";
import { useAuth } from "../auth/useAuth";
import {
  FieldErrors,
  TouchedFields,
  getFieldErrorId,
  getTextInputClass,
  getVisibleFieldError,
  hasAnyFieldError,
  touchFields,
} from "../forms/fieldValidation";
import { TokenUsage } from "../api/types";

type ProfileField = "username";

interface ProfileValues {
  username: string;
}

const profileFields: readonly ProfileField[] = ["username"];

function validateProfileValues(
  values: ProfileValues
): FieldErrors<ProfileField> {
  const errors: FieldErrors<ProfileField> = {};
  const normalisedUsername = values.username.trim();

  if (!normalisedUsername) {
    errors.username = "Please enter a username.";
  } else if (normalisedUsername.length < 3 || normalisedUsername.length > 50) {
    errors.username = "Username must be between 3 and 50 characters.";
  }

  return errors;
}

function mapProfileError(message: string): FieldErrors<ProfileField> | null {
  if (message === "Username already taken") {
    return { username: message };
  }
  return null;
}

export function ProfilePage() {
  const { user, updateProfile, deleteAccount } = useAuth();
  const [username, setUsername] = useState(user?.username ?? "");
  const [programmingLevel, setProgrammingLevel] = useState(
    user?.programming_level ?? 3
  );
  const [mathsLevel, setMathsLevel] = useState(user?.maths_level ?? 3);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isDeletingAccount, setIsDeletingAccount] = useState(false);
  const [successMessage, setSuccessMessage] = useState("");
  const [error, setError] = useState("");
  const [deleteAccountError, setDeleteAccountError] = useState("");
  const [fieldErrors, setFieldErrors] = useState<FieldErrors<ProfileField>>({});
  const [touchedFields, setTouchedFields] = useState<TouchedFields<ProfileField>>(
    {}
  );
  const [usage, setUsage] = useState<TokenUsage | null>(null);

  const oneDpFormatter = new Intl.NumberFormat("en-GB", {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  });

  useEffect(() => {
    apiFetch<TokenUsage>("/api/chat/usage")
      .then(setUsage)
      .catch((err) => console.error("Failed to fetch usage:", err));
  }, []);

  useEffect(() => {
    setUsername(user?.username ?? "");
    setProgrammingLevel(user?.programming_level ?? 3);
    setMathsLevel(user?.maths_level ?? 3);
  }, [user]);

  if (!user) {
    return null;
  }

  const syncValidation = (nextValues: ProfileValues) => {
    setFieldErrors(validateProfileValues(nextValues));
  };

  const handleBlur = () => {
    setTouchedFields((current) => touchFields(current, profileFields));
    syncValidation({ username });
  };

  const handleUsernameChange = (nextUsername: string) => {
    setUsername(nextUsername);
    setError("");
    setDeleteAccountError("");
    setSuccessMessage("");
    if (touchedFields.username || hasAnyFieldError(fieldErrors)) {
      syncValidation({ username: nextUsername });
    }
  };

  const handleProfileSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setError("");
    setDeleteAccountError("");
    setSuccessMessage("");
    const nextValues = { username };
    const nextErrors = validateProfileValues(nextValues);
    setFieldErrors(nextErrors);
    setTouchedFields((current) => touchFields(current, profileFields));
    if (hasAnyFieldError(nextErrors)) {
      return;
    }

    setIsSubmitting(true);
    try {
      await updateProfile({
        username: username.trim(),
        programming_level: programmingLevel,
        maths_level: mathsLevel,
      });
      setSuccessMessage("Profile updated successfully.");
    } catch (err) {
      const message = err instanceof Error ? err.message : "Update failed.";
      const mappedErrors = mapProfileError(message);
      if (mappedErrors) {
        setFieldErrors(mappedErrors);
        setTouchedFields((current) => touchFields(current, profileFields));
        return;
      }
      setError(message);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleDeleteAccount = async () => {
    setError("");
    setDeleteAccountError("");
    setSuccessMessage("");

    const confirmed = window.confirm(
      "Deleting your account permanently removes your profile, chats, uploads, personal notebooks, and Learning Hub progress. You will need to register again to use Guided Cursor."
    );
    if (!confirmed) {
      return;
    }

    setIsDeletingAccount(true);
    try {
      await deleteAccount();
      window.location.replace("/register");
    } catch (err) {
      const message = err instanceof Error ? err.message : "Account deletion failed.";
      setDeleteAccountError(message);
    } finally {
      setIsDeletingAccount(false);
    }
  };

  const levelLabels = ["Beginner", "Elementary", "Intermediate", "Advanced", "Expert"];
  const formatDate = (value: string) =>
    new Date(`${value}T00:00:00`).toLocaleDateString("en-GB", {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  const usernameError = getVisibleFieldError(
    "username",
    fieldErrors,
    touchedFields
  );

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-lg mx-auto py-8 px-4 space-y-6">
        {/* Profile info */}
        <div className="bg-white rounded-lg shadow-md p-8">
          <h1 className="text-2xl font-bold text-center text-brand mb-6">Profile</h1>

          {error && (
            <div className="px-4 py-3 rounded mb-4 bg-red-100 border border-red-400 text-red-700">
              {error}
            </div>
          )}
          {successMessage && (
            <div className="px-4 py-3 rounded mb-4 bg-green-100 border border-green-400 text-green-700">
              {successMessage}
            </div>
          )}

          <div className="space-y-2 mb-6">
            <div>
              <span className="text-sm font-medium text-gray-700">Email:</span>
              <p className="text-gray-900">{user.email}</p>
            </div>
            <div className="flex items-center justify-between gap-3">
              <div className="text-gray-900">
                <span className="text-sm font-medium text-gray-700">Password:</span>{" "}
                <span>********</span>
              </div>
              <Link
                to="/profile/reset-password/password"
                className="inline-flex rounded-md bg-brand px-4 py-2 text-sm font-medium text-white hover:bg-brand-light focus:outline-none focus:ring-2 focus:ring-accent"
              >
                Reset Password
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

          <form onSubmit={handleProfileSubmit} noValidate className="space-y-4">
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
                onBlur={handleBlur}
                onChange={(event) => handleUsernameChange(event.target.value)}
                className={getTextInputClass(Boolean(usernameError))}
                aria-invalid={Boolean(usernameError)}
                aria-describedby={
                  usernameError
                    ? getFieldErrorId("profile", "username")
                    : undefined
                }
                minLength={3}
                maxLength={50}
              />
              {usernameError && (
                <p
                  id={getFieldErrorId("profile", "username")}
                  className="mt-1 text-sm text-red-600"
                >
                  {usernameError}
                </p>
              )}
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
                onChange={(event) =>
                  setProgrammingLevel(parseInt(event.target.value, 10))
                }
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
                onChange={(event) =>
                  setMathsLevel(parseInt(event.target.value, 10))
                }
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

        {/* Weekly usage */}
        {usage && (
          <div className="bg-white rounded-lg shadow-md p-6">
            <h2 className="text-lg font-bold text-brand mb-1">Weekly Token Budget</h2>
            <p className="text-sm text-gray-600 mb-4">
              {formatDate(usage.week_start)} to {formatDate(usage.week_end)}
            </p>

            <div
              className="w-full bg-gray-200 rounded-full h-4 mb-2"
              aria-label="Weekly token budget usage"
            >
              <div
                className="bg-accent h-4 rounded-full transition-all"
                style={{ width: `${Math.min(usage.usage_percentage, 100)}%` }}
              />
            </div>
            <p className="text-sm text-gray-600">
              {oneDpFormatter.format(usage.usage_percentage)}% used
            </p>
          </div>
        )}

        <div className="bg-white rounded-lg shadow-md border border-red-200 p-6">
          <h2 className="text-lg font-bold text-red-700 mb-2">Delete Account</h2>
          <p className="text-sm text-gray-700">
            Deleting your account permanently removes your profile, chats,
            uploads, personal notebooks, and Learning Hub progress.
          </p>
          <p className="mt-2 text-sm text-gray-700">
            After deletion, you will need to register again before you can use
            Guided Cursor.
          </p>
          {deleteAccountError && (
            <div className="mt-4 rounded border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-700">
              {deleteAccountError}
            </div>
          )}
          <button
            type="button"
            onClick={handleDeleteAccount}
            disabled={isDeletingAccount}
            className="mt-5 w-full rounded-md bg-red-600 px-4 py-2 text-white hover:bg-red-700 focus:outline-none focus:ring-2 focus:ring-red-300 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {isDeletingAccount ? "Deleting account..." : "Delete Account"}
          </button>
        </div>
      </div>
    </div>
  );
}
