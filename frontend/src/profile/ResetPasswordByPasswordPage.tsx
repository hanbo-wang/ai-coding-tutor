import { FormEvent, useState } from "react";
import { Link } from "react-router-dom";
import {
  FieldErrors,
  TouchedFields,
  getFieldErrorId,
  getTextInputClass,
  getVisibleFieldError,
  hasAnyFieldError,
  touchFields,
} from "../forms/fieldValidation";
import { useAuth } from "../auth/useAuth";

type ResetByPasswordField =
  | "currentPassword"
  | "newPassword"
  | "confirmNewPassword";

interface ResetByPasswordValues {
  currentPassword: string;
  newPassword: string;
  confirmNewPassword: string;
}

const resetByPasswordFields: readonly ResetByPasswordField[] = [
  "currentPassword",
  "newPassword",
  "confirmNewPassword",
];

function validateResetByPasswordValues(
  values: ResetByPasswordValues
): FieldErrors<ResetByPasswordField> {
  const errors: FieldErrors<ResetByPasswordField> = {};

  if (!values.currentPassword) {
    errors.currentPassword = "Please enter your current password.";
  }

  if (!values.newPassword) {
    errors.newPassword = "Please enter a new password.";
  } else if (values.newPassword.length < 8) {
    errors.newPassword = "Password must be at least 8 characters.";
  }

  if (!values.confirmNewPassword) {
    errors.confirmNewPassword = "Please confirm your new password.";
  } else if (values.newPassword !== values.confirmNewPassword) {
    errors.confirmNewPassword = "Passwords do not match.";
  }

  return errors;
}

function mapResetByPasswordError(
  message: string
): FieldErrors<ResetByPasswordField> | null {
  if (message === "Current password is incorrect.") {
    return { currentPassword: message };
  }
  return null;
}

export function ResetPasswordByPasswordPage() {
  const { changePassword } = useAuth();
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmNewPassword, setConfirmNewPassword] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [fieldErrors, setFieldErrors] = useState<
    FieldErrors<ResetByPasswordField>
  >({});
  const [touchedFields, setTouchedFields] = useState<
    TouchedFields<ResetByPasswordField>
  >({});
  const [isSubmitting, setIsSubmitting] = useState(false);

  const getCurrentValues = (
    overrides: Partial<ResetByPasswordValues> = {}
  ): ResetByPasswordValues => ({
    currentPassword,
    newPassword,
    confirmNewPassword,
    ...overrides,
  });

  const syncValidation = (nextValues: ResetByPasswordValues) => {
    setFieldErrors(validateResetByPasswordValues(nextValues));
  };

  const handleBlur = (field: ResetByPasswordField) => {
    setTouchedFields((current) => touchFields(current, [field]));
    syncValidation(getCurrentValues());
  };

  const handleFieldChange = (
    field: ResetByPasswordField,
    nextValue: string,
    apply: () => void
  ) => {
    apply();
    setError("");
    setMessage("");
    const nextValues = getCurrentValues({ [field]: nextValue });
    if (touchedFields[field] || hasAnyFieldError(fieldErrors)) {
      syncValidation(nextValues);
    }
  };

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setError("");
    setMessage("");
    const nextValues = getCurrentValues();
    const nextErrors = validateResetByPasswordValues(nextValues);
    setFieldErrors(nextErrors);
    setTouchedFields((current) =>
      touchFields(current, resetByPasswordFields)
    );
    if (hasAnyFieldError(nextErrors)) {
      return;
    }

    setIsSubmitting(true);
    try {
      await changePassword({
        current_password: nextValues.currentPassword,
        new_password: nextValues.newPassword,
      });
      setMessage("Password reset successfully.");
      setCurrentPassword("");
      setNewPassword("");
      setConfirmNewPassword("");
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Password reset failed.";
      const mappedErrors = mapResetByPasswordError(message);
      if (mappedErrors) {
        const mappedFields = Object.keys(mappedErrors) as ResetByPasswordField[];
        setFieldErrors(mappedErrors);
        setTouchedFields((current) => touchFields(current, mappedFields));
        return;
      }
      setError(message);
    } finally {
      setIsSubmitting(false);
    }
  };

  const currentPasswordError = getVisibleFieldError(
    "currentPassword",
    fieldErrors,
    touchedFields
  );
  const newPasswordError = getVisibleFieldError(
    "newPassword",
    fieldErrors,
    touchedFields
  );
  const confirmNewPasswordError = getVisibleFieldError(
    "confirmNewPassword",
    fieldErrors,
    touchedFields
  );

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-md mx-auto py-8 px-4">
        <div className="bg-white rounded-lg shadow-md p-8">
          <h1 className="text-2xl font-bold text-center text-brand mb-2">
            Reset Password
          </h1>
          <p className="text-center text-gray-500 mb-6">
            Use your current password to set a new one
          </p>

          {error && (
            <div className="bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded mb-4">
              {error}
            </div>
          )}
          {message && (
            <div className="bg-green-100 border border-green-400 text-green-700 px-4 py-3 rounded mb-4">
              {message}
            </div>
          )}

          <form onSubmit={handleSubmit} noValidate className="space-y-4">
            <div>
              <label
                htmlFor="currentPassword"
                className="block text-sm font-medium text-gray-700 mb-1"
              >
                Current Password
              </label>
              <input
                type="password"
                id="currentPassword"
                value={currentPassword}
                onBlur={() => handleBlur("currentPassword")}
                onChange={(event) =>
                  handleFieldChange("currentPassword", event.target.value, () => {
                    setCurrentPassword(event.target.value);
                  })
                }
                className={getTextInputClass(Boolean(currentPasswordError))}
                aria-invalid={Boolean(currentPasswordError)}
                aria-describedby={
                  currentPasswordError
                    ? getFieldErrorId("reset-password", "currentPassword")
                    : undefined
                }
              />
              {currentPasswordError && (
                <p
                  id={getFieldErrorId("reset-password", "currentPassword")}
                  className="mt-1 text-sm text-red-600"
                >
                  {currentPasswordError}
                </p>
              )}
            </div>

            <div>
              <label
                htmlFor="newPassword"
                className="block text-sm font-medium text-gray-700 mb-1"
              >
                New Password
              </label>
              <input
                type="password"
                id="newPassword"
                value={newPassword}
                onBlur={() => handleBlur("newPassword")}
                onChange={(event) =>
                  handleFieldChange("newPassword", event.target.value, () => {
                    setNewPassword(event.target.value);
                  })
                }
                className={getTextInputClass(Boolean(newPasswordError))}
                aria-invalid={Boolean(newPasswordError)}
                aria-describedby={
                  newPasswordError
                    ? getFieldErrorId("reset-password", "newPassword")
                    : undefined
                }
                minLength={8}
              />
              {newPasswordError && (
                <p
                  id={getFieldErrorId("reset-password", "newPassword")}
                  className="mt-1 text-sm text-red-600"
                >
                  {newPasswordError}
                </p>
              )}
            </div>

            <div>
              <label
                htmlFor="confirmNewPassword"
                className="block text-sm font-medium text-gray-700 mb-1"
              >
                Confirm New Password
              </label>
              <input
                type="password"
                id="confirmNewPassword"
                value={confirmNewPassword}
                onBlur={() => handleBlur("confirmNewPassword")}
                onChange={(event) =>
                  handleFieldChange(
                    "confirmNewPassword",
                    event.target.value,
                    () => {
                      setConfirmNewPassword(event.target.value);
                    }
                  )
                }
                className={getTextInputClass(Boolean(confirmNewPasswordError))}
                aria-invalid={Boolean(confirmNewPasswordError)}
                aria-describedby={
                  confirmNewPasswordError
                    ? getFieldErrorId("reset-password", "confirmNewPassword")
                    : undefined
                }
              />
              {confirmNewPasswordError && (
                <p
                  id={getFieldErrorId("reset-password", "confirmNewPassword")}
                  className="mt-1 text-sm text-red-600"
                >
                  {confirmNewPasswordError}
                </p>
              )}
            </div>

            <button
              type="submit"
              disabled={isSubmitting}
              className="w-full bg-brand text-white py-2 px-4 rounded-md hover:bg-brand-light focus:outline-none focus:ring-2 focus:ring-accent disabled:opacity-50"
            >
              {isSubmitting ? "Resetting..." : "Reset Password"}
            </button>
          </form>

          <p className="mt-4 text-center text-sm text-gray-600">
            Prefer email verification?{" "}
            <Link
              to="/profile/reset-password/email"
              className="text-accent-dark hover:underline"
            >
              Use email
            </Link>
          </p>
          <p className="mt-2 text-center text-sm text-gray-600">
            <Link to="/profile" className="text-accent-dark hover:underline">
              Back to profile
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
