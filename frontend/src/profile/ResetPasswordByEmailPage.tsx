import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  FieldErrors,
  TouchedFields,
  getFieldErrorId,
  getReadOnlyInputClass,
  getTextInputClass,
  getVisibleFieldError,
  hasAnyFieldError,
  isValidVerificationCode,
  touchFields,
} from "../forms/fieldValidation";
import { useAuth } from "../auth/useAuth";

type ResetByEmailField =
  | "verificationCode"
  | "newPassword"
  | "confirmNewPassword";

interface ResetByEmailValues {
  verificationCode: string;
  newPassword: string;
  confirmNewPassword: string;
}

const resetByEmailFields: readonly ResetByEmailField[] = [
  "verificationCode",
  "newPassword",
  "confirmNewPassword",
];

function validateResetByEmailValues(
  values: ResetByEmailValues
): FieldErrors<ResetByEmailField> {
  const errors: FieldErrors<ResetByEmailField> = {};

  if (!values.verificationCode || !isValidVerificationCode(values.verificationCode)) {
    errors.verificationCode = "Please enter a valid 6-digit verification code.";
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

function mapResetByEmailError(
  message: string
): FieldErrors<ResetByEmailField> | null {
  if (message === "Invalid or expired verification code") {
    return { verificationCode: message };
  }
  return null;
}

export function ResetPasswordByEmailPage() {
  const { user, sendPasswordResetCode, resetPassword } = useAuth();
  const [verificationCode, setVerificationCode] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmNewPassword, setConfirmNewPassword] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [fieldErrors, setFieldErrors] = useState<FieldErrors<ResetByEmailField>>(
    {}
  );
  const [touchedFields, setTouchedFields] = useState<TouchedFields<ResetByEmailField>>(
    {}
  );
  const [isSendingCode, setIsSendingCode] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [resendCooldown, setResendCooldown] = useState(0);

  useEffect(() => {
    if (resendCooldown <= 0) {
      return;
    }
    const timer = window.setInterval(() => {
      setResendCooldown((value) => (value > 0 ? value - 1 : 0));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [resendCooldown]);

  if (!user) {
    return null;
  }

  const getCurrentValues = (
    overrides: Partial<ResetByEmailValues> = {}
  ): ResetByEmailValues => ({
    verificationCode,
    newPassword,
    confirmNewPassword,
    ...overrides,
  });

  const syncValidation = (nextValues: ResetByEmailValues) => {
    setFieldErrors(validateResetByEmailValues(nextValues));
  };

  const handleBlur = (field: ResetByEmailField) => {
    setTouchedFields((current) => touchFields(current, [field]));
    syncValidation(getCurrentValues());
  };

  const handleFieldChange = (
    field: ResetByEmailField,
    nextValue: string,
    apply: () => void
  ) => {
    apply();
    setError("");
    const nextValues = getCurrentValues({ [field]: nextValue });
    if (touchedFields[field] || hasAnyFieldError(fieldErrors)) {
      syncValidation(nextValues);
    }
  };

  const handleSendCode = async () => {
    setError("");
    setMessage("");
    setIsSendingCode(true);
    try {
      const sendCodeResponse = await sendPasswordResetCode(user.email);
      setMessage(`${sendCodeResponse.message} Please check your inbox.`);
      setResendCooldown(sendCodeResponse.resend_cooldown_seconds);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to send code.");
    } finally {
      setIsSendingCode(false);
    }
  };

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setError("");
    setMessage("");
    const nextValues = getCurrentValues();
    const nextErrors = validateResetByEmailValues(nextValues);
    setFieldErrors(nextErrors);
    setTouchedFields((current) => touchFields(current, resetByEmailFields));
    if (hasAnyFieldError(nextErrors)) {
      return;
    }

    setIsSubmitting(true);
    try {
      await resetPassword({
        email: user.email,
        verification_code: nextValues.verificationCode,
        new_password: nextValues.newPassword,
      });
      setMessage("Password reset successfully.");
      setVerificationCode("");
      setNewPassword("");
      setConfirmNewPassword("");
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Password reset failed.";
      const mappedErrors = mapResetByEmailError(message);
      if (mappedErrors) {
        const mappedFields = Object.keys(mappedErrors) as ResetByEmailField[];
        setFieldErrors(mappedErrors);
        setTouchedFields((current) => touchFields(current, mappedFields));
        return;
      }
      setError(message);
    } finally {
      setIsSubmitting(false);
    }
  };

  const verificationCodeError = getVisibleFieldError(
    "verificationCode",
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
            Verify your account email to set a new password
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
              <div className="mb-1 flex items-center justify-between gap-3">
                <label
                  htmlFor="email"
                  className="block text-sm font-medium text-gray-700"
                >
                  Account Email
                </label>
                <button
                  type="button"
                  onClick={handleSendCode}
                  disabled={isSendingCode || resendCooldown > 0}
                  className="rounded-md border border-gray-300 px-3 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {isSendingCode
                    ? "Sending..."
                    : resendCooldown > 0
                      ? `Resend in ${resendCooldown}s`
                      : "Send code"}
                </button>
              </div>
              <input
                type="email"
                id="email"
                value={user.email}
                className={getReadOnlyInputClass()}
                readOnly
              />
            </div>

            <div>
              <label
                htmlFor="verificationCode"
                className="block text-sm font-medium text-gray-700 mb-1"
              >
                Verification Code
              </label>
              <input
                type="text"
                id="verificationCode"
                value={verificationCode}
                onBlur={() => handleBlur("verificationCode")}
                onChange={(event) =>
                  handleFieldChange(
                    "verificationCode",
                    event.target.value.replace(/\D/g, "").slice(0, 6),
                    () => {
                      setVerificationCode(
                        event.target.value.replace(/\D/g, "").slice(0, 6)
                      );
                    }
                  )
                }
                className={getTextInputClass(Boolean(verificationCodeError))}
                aria-invalid={Boolean(verificationCodeError)}
                aria-describedby={
                  verificationCodeError
                    ? getFieldErrorId("reset-email", "verificationCode")
                    : undefined
                }
                maxLength={6}
                inputMode="numeric"
                pattern="\d{6}"
                placeholder="Enter 6-digit code"
              />
              {verificationCodeError && (
                <p
                  id={getFieldErrorId("reset-email", "verificationCode")}
                  className="mt-1 text-sm text-red-600"
                >
                  {verificationCodeError}
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
                    ? getFieldErrorId("reset-email", "newPassword")
                    : undefined
                }
                minLength={8}
              />
              {newPasswordError && (
                <p
                  id={getFieldErrorId("reset-email", "newPassword")}
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
                    ? getFieldErrorId("reset-email", "confirmNewPassword")
                    : undefined
                }
              />
              {confirmNewPasswordError && (
                <p
                  id={getFieldErrorId("reset-email", "confirmNewPassword")}
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
            Prefer your current password?{" "}
            <Link
              to="/profile/reset-password/password"
              className="text-accent-dark hover:underline"
            >
              Use current password
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
