import { FormEvent, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  FieldErrors,
  TouchedFields,
  getFieldErrorId,
  getTextInputClass,
  getVisibleFieldError,
  hasAnyFieldError,
  isValidEmail,
  isValidVerificationCode,
  touchFields,
} from "../forms/fieldValidation";
import { useAuth } from "./useAuth";

type ForgotPasswordField =
  | "email"
  | "verificationCode"
  | "newPassword"
  | "confirmNewPassword";

interface ForgotPasswordValues {
  email: string;
  verificationCode: string;
  newPassword: string;
  confirmNewPassword: string;
}

const forgotPasswordFields: readonly ForgotPasswordField[] = [
  "email",
  "verificationCode",
  "newPassword",
  "confirmNewPassword",
];

const forgotPasswordSendCodeFields: readonly ForgotPasswordField[] = ["email"];

function validateForgotPasswordValues(
  values: ForgotPasswordValues
): FieldErrors<ForgotPasswordField> {
  const errors: FieldErrors<ForgotPasswordField> = {};
  const normalisedEmail = values.email.trim();

  if (!normalisedEmail) {
    errors.email = "Please enter your email first.";
  } else if (!isValidEmail(normalisedEmail)) {
    errors.email = "Please enter a valid email address.";
  }

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

function mapForgotPasswordError(
  message: string
): FieldErrors<ForgotPasswordField> | null {
  if (message === "Email is not registered.") {
    return { email: message };
  }
  if (message === "Invalid or expired verification code") {
    return { verificationCode: message };
  }
  return null;
}

export function ForgotPasswordPage() {
  const { sendPasswordResetCode, resetPassword } = useAuth();
  const navigate = useNavigate();

  const [email, setEmail] = useState("");
  const [verificationCode, setVerificationCode] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmNewPassword, setConfirmNewPassword] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [fieldErrors, setFieldErrors] = useState<
    FieldErrors<ForgotPasswordField>
  >({});
  const [touchedFields, setTouchedFields] = useState<
    TouchedFields<ForgotPasswordField>
  >({});
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

  const getCurrentValues = (
    overrides: Partial<ForgotPasswordValues> = {}
  ): ForgotPasswordValues => ({
    email,
    verificationCode,
    newPassword,
    confirmNewPassword,
    ...overrides,
  });

  const syncValidation = (nextValues: ForgotPasswordValues) => {
    setFieldErrors(validateForgotPasswordValues(nextValues));
  };

  const handleBlur = (field: ForgotPasswordField) => {
    setTouchedFields((current) => touchFields(current, [field]));
    syncValidation(getCurrentValues());
  };

  const handleFieldChange = (
    field: ForgotPasswordField,
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
    const nextValues = getCurrentValues();
    const nextErrors = validateForgotPasswordValues(nextValues);
    setFieldErrors(nextErrors);
    setTouchedFields((current) =>
      touchFields(current, forgotPasswordSendCodeFields)
    );
    if (hasAnyFieldError(nextErrors, forgotPasswordSendCodeFields)) {
      return;
    }

    setIsSendingCode(true);
    try {
      const sendCodeResponse = await sendPasswordResetCode(
        nextValues.email.trim()
      );
      setMessage(`${sendCodeResponse.message} Please check your inbox.`);
      setResendCooldown(sendCodeResponse.resend_cooldown_seconds);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to send code.";
      const mappedErrors = mapForgotPasswordError(message);
      if (mappedErrors) {
        const mappedFields = Object.keys(mappedErrors) as ForgotPasswordField[];
        setFieldErrors(mappedErrors);
        setTouchedFields((current) => touchFields(current, mappedFields));
        return;
      }
      setError(message);
    } finally {
      setIsSendingCode(false);
    }
  };

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setError("");
    setMessage("");
    const nextValues = getCurrentValues();
    const nextErrors = validateForgotPasswordValues(nextValues);
    setFieldErrors(nextErrors);
    setTouchedFields((current) => touchFields(current, forgotPasswordFields));
    if (hasAnyFieldError(nextErrors)) {
      return;
    }

    setIsSubmitting(true);
    try {
      await resetPassword({
        email: nextValues.email.trim(),
        verification_code: nextValues.verificationCode,
        new_password: nextValues.newPassword,
      });
      setMessage("Password reset successfully. You can now log in.");
      setVerificationCode("");
      setNewPassword("");
      setConfirmNewPassword("");
      window.setTimeout(() => navigate("/login"), 1200);
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Password reset failed.";
      const mappedErrors = mapForgotPasswordError(message);
      if (mappedErrors) {
        const mappedFields = Object.keys(mappedErrors) as ForgotPasswordField[];
        setFieldErrors(mappedErrors);
        setTouchedFields((current) => touchFields(current, mappedFields));
        return;
      }
      setError(message);
    } finally {
      setIsSubmitting(false);
    }
  };

  const emailError = getVisibleFieldError("email", fieldErrors, touchedFields);
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
            Forgot Password
          </h1>
          <p className="text-center text-gray-500 mb-6">
            Use your email verification code to set a new password
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
                  Email
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
                value={email}
                onBlur={() => handleBlur("email")}
                onChange={(event) =>
                  handleFieldChange("email", event.target.value, () => {
                    setEmail(event.target.value);
                  })
                }
                className={getTextInputClass(Boolean(emailError))}
                aria-invalid={Boolean(emailError)}
                aria-describedby={
                  emailError
                    ? getFieldErrorId("forgot-password", "email")
                    : undefined
                }
              />
              {emailError && (
                <p
                  id={getFieldErrorId("forgot-password", "email")}
                  className="mt-1 text-sm text-red-600"
                >
                  {emailError}
                </p>
              )}
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
                    ? getFieldErrorId("forgot-password", "verificationCode")
                    : undefined
                }
                maxLength={6}
                inputMode="numeric"
                pattern="\d{6}"
                placeholder="Enter 6-digit code"
              />
              {verificationCodeError && (
                <p
                  id={getFieldErrorId("forgot-password", "verificationCode")}
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
                    ? getFieldErrorId("forgot-password", "newPassword")
                    : undefined
                }
                minLength={8}
              />
              {newPasswordError && (
                <p
                  id={getFieldErrorId("forgot-password", "newPassword")}
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
                    ? getFieldErrorId("forgot-password", "confirmNewPassword")
                    : undefined
                }
              />
              {confirmNewPasswordError && (
                <p
                  id={getFieldErrorId("forgot-password", "confirmNewPassword")}
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
            Back to{" "}
            <Link to="/login" className="text-accent-dark hover:underline">
              Login
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
