import { FormEvent, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { apiFetch } from "../api/http";
import { RegistrationPolicy } from "../api/types";
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
import { UserNoticeDialog } from "./UserNoticeDialog";
import { useAuth } from "./useAuth";

const UCL_DOMAIN_PATTERN = /@ucl\.ac\.uk$/i;
const UCL_STUDENT_EMAIL_PATTERN = /^[a-z0-9]+(?:\.[a-z0-9]+)*\.[0-9]+@ucl\.ac\.uk$/;
const REGISTRATION_EMAIL_POLICY_DETAIL =
  "Registration is limited to UCL student emails in the format " +
  "name.name.<digits>@ucl.ac.uk. Configured admin emails are exempt.";
const USER_NOTICE_ACCEPTANCE_DETAIL =
  "Please accept the Guided Cursor user notice.";

type RegisterField =
  | "email"
  | "verificationCode"
  | "username"
  | "password"
  | "confirmPassword"
  | "acceptedUserNotice";

interface RegisterValues {
  email: string;
  verificationCode: string;
  username: string;
  password: string;
  confirmPassword: string;
  acceptedUserNotice: boolean;
}

const registerFields: readonly RegisterField[] = [
  "email",
  "verificationCode",
  "username",
  "password",
  "confirmPassword",
  "acceptedUserNotice",
];

const registerSendCodeFields: readonly RegisterField[] = ["email", "username"];

function getRegistrationEmailError(
  value: string,
  enableUclRegistrationEmailPolicy: boolean
): string | null {
  if (!enableUclRegistrationEmailPolicy) {
    return null;
  }
  if (!UCL_STUDENT_EMAIL_PATTERN.test(value.toLowerCase())) {
    if (UCL_DOMAIN_PATTERN.test(value)) {
      return null;
    }
    return REGISTRATION_EMAIL_POLICY_DETAIL;
  }
  return null;
}

function getRegistrationEmailHint(
  value: string,
  enableUclRegistrationEmailPolicy: boolean
): string {
  if (
    !enableUclRegistrationEmailPolicy ||
    !value ||
    UCL_STUDENT_EMAIL_PATTERN.test(value.toLowerCase()) ||
    !UCL_DOMAIN_PATTERN.test(value)
  ) {
    return "";
  }
  return (
    "This address is not in the student-format pattern. " +
    "If it is an admin email, the server may still allow registration."
  );
}

function validateRegisterValues(
  values: RegisterValues,
  enableUclRegistrationEmailPolicy: boolean
): FieldErrors<RegisterField> {
  const errors: FieldErrors<RegisterField> = {};
  const normalisedEmail = values.email.trim();
  const normalisedUsername = values.username.trim();

  if (!normalisedEmail) {
    errors.email = "Please enter your email first.";
  } else if (!isValidEmail(normalisedEmail)) {
    errors.email = "Please enter a valid email address.";
  } else {
    const registrationEmailError = getRegistrationEmailError(
      normalisedEmail,
      enableUclRegistrationEmailPolicy
    );
    if (registrationEmailError) {
      errors.email = registrationEmailError;
    }
  }

  if (!values.verificationCode || !isValidVerificationCode(values.verificationCode)) {
    errors.verificationCode = "Please enter a valid 6-digit verification code.";
  }

  if (!normalisedUsername) {
    errors.username = "Please enter a username.";
  } else if (normalisedUsername.length < 3 || normalisedUsername.length > 50) {
    errors.username = "Username must be between 3 and 50 characters.";
  }

  if (!values.password) {
    errors.password = "Please enter a password.";
  } else if (values.password.length < 8) {
    errors.password = "Password must be at least 8 characters.";
  }

  if (!values.confirmPassword) {
    errors.confirmPassword = "Please confirm your password.";
  } else if (values.password !== values.confirmPassword) {
    errors.confirmPassword = "Passwords do not match.";
  }

  if (!values.acceptedUserNotice) {
    errors.acceptedUserNotice = USER_NOTICE_ACCEPTANCE_DETAIL;
  }

  return errors;
}

function mapRegisterError(message: string): FieldErrors<RegisterField> | null {
  if (
    message === "Email already registered" ||
    message === REGISTRATION_EMAIL_POLICY_DETAIL
  ) {
    return { email: message };
  }
  if (message === "Username already taken") {
    return { username: message };
  }
  if (message === "Invalid or expired verification code") {
    return { verificationCode: message };
  }
  if (message === USER_NOTICE_ACCEPTANCE_DETAIL) {
    return { acceptedUserNotice: message };
  }
  return null;
}

export function RegisterPage() {
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [verificationCode, setVerificationCode] = useState("");
  const [acceptedUserNotice, setAcceptedUserNotice] = useState(false);
  const [codeMessage, setCodeMessage] = useState("");
  const [programmingLevel, setProgrammingLevel] = useState(3);
  const [mathsLevel, setMathsLevel] = useState(3);
  const [error, setError] = useState("");
  const [emailHint, setEmailHint] = useState("");
  const [enableUclRegistrationEmailPolicy, setEnableUclRegistrationEmailPolicy] =
    useState(false);
  const [fieldErrors, setFieldErrors] = useState<FieldErrors<RegisterField>>(
    {}
  );
  const [touchedFields, setTouchedFields] = useState<TouchedFields<RegisterField>>(
    {}
  );
  const [isSendingCode, setIsSendingCode] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [resendCooldown, setResendCooldown] = useState(0);
  const [isUserNoticeOpen, setIsUserNoticeOpen] = useState(false);
  const { register, sendRegisterCode } = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    let isActive = true;

    apiFetch<RegistrationPolicy>("/api/auth/register/policy")
      .then((policy) => {
        if (!isActive) {
          return;
        }
        setEnableUclRegistrationEmailPolicy(
          policy.enable_ucl_registration_email_policy
        );
      })
      .catch(() => {
        if (!isActive) {
          return;
        }
        // Fall back to generic client-side email checks; the backend stays authoritative.
        setEnableUclRegistrationEmailPolicy(false);
      });

    return () => {
      isActive = false;
    };
  }, []);

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
    overrides: Partial<RegisterValues> = {}
  ): RegisterValues => ({
    email,
    verificationCode,
    username,
    password,
    confirmPassword,
    acceptedUserNotice,
    ...overrides,
  });

  const syncValidation = (nextValues: RegisterValues) => {
    setFieldErrors(
      validateRegisterValues(nextValues, enableUclRegistrationEmailPolicy)
    );
  };

  const handleBlur = (field: RegisterField) => {
    setTouchedFields((current) => touchFields(current, [field]));
    syncValidation(getCurrentValues());
  };

  const handleFieldChange = (
    field: RegisterField,
    nextValue: string,
    apply: () => void
  ) => {
    apply();
    setError("");
    const nextValues = getCurrentValues({ [field]: nextValue });

    if (field === "email") {
      setEmailHint(
        getRegistrationEmailHint(
          nextValues.email.trim(),
          enableUclRegistrationEmailPolicy
        )
      );
    }

    if (touchedFields[field] || hasAnyFieldError(fieldErrors)) {
      syncValidation(nextValues);
    }
  };

  const handleSendCode = async () => {
    setError("");
    setCodeMessage("");
    const nextValues = getCurrentValues();
    const nextErrors = validateRegisterValues(
      nextValues,
      enableUclRegistrationEmailPolicy
    );
    setFieldErrors(nextErrors);
    setTouchedFields((current) => touchFields(current, registerSendCodeFields));
    if (hasAnyFieldError(nextErrors, registerSendCodeFields)) {
      return;
    }

    const normalisedEmail = nextValues.email.trim();
    const normalisedUsername = nextValues.username.trim();
    setEmailHint(
      getRegistrationEmailHint(
        normalisedEmail,
        enableUclRegistrationEmailPolicy
      )
    );

    setIsSendingCode(true);
    try {
      const sendCodeResponse = await sendRegisterCode(
        normalisedEmail,
        normalisedUsername
      );
      setCodeMessage(`${sendCodeResponse.message} Please check your inbox.`);
      // Keep the UI countdown aligned with the backend cooldown rule.
      setResendCooldown(sendCodeResponse.resend_cooldown_seconds);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to send code.";
      const mappedErrors = mapRegisterError(message);
      if (mappedErrors) {
        const mappedFields = Object.keys(mappedErrors) as RegisterField[];
        setFieldErrors(mappedErrors);
        setTouchedFields((current) => touchFields(current, mappedFields));
        return;
      }
      setError(message);
    } finally {
      setIsSendingCode(false);
    }
  };

  const handleAcceptedUserNoticeChange = (nextAcceptedUserNotice: boolean) => {
    setAcceptedUserNotice(nextAcceptedUserNotice);
    setError("");
    const nextValues = getCurrentValues({
      acceptedUserNotice: nextAcceptedUserNotice,
    });

    if (touchedFields.acceptedUserNotice || hasAnyFieldError(fieldErrors)) {
      syncValidation(nextValues);
    }
  };

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setError("");
    setCodeMessage("");
    const nextValues = getCurrentValues();
    const nextErrors = validateRegisterValues(
      nextValues,
      enableUclRegistrationEmailPolicy
    );
    setFieldErrors(nextErrors);
    setTouchedFields((current) => touchFields(current, registerFields));
    if (hasAnyFieldError(nextErrors)) {
      return;
    }

    const normalisedEmail = nextValues.email.trim();
    const normalisedUsername = nextValues.username.trim();
    setEmailHint(
      getRegistrationEmailHint(
        normalisedEmail,
        enableUclRegistrationEmailPolicy
      )
    );
    setIsSubmitting(true);

    try {
      await register({
        email: normalisedEmail,
        username: normalisedUsername,
        password,
        verification_code: verificationCode,
        accepted_user_notice: nextValues.acceptedUserNotice,
        programming_level: programmingLevel,
        maths_level: mathsLevel,
      });
      navigate("/chat");
    } catch (err) {
      const message = err instanceof Error ? err.message : "Registration failed.";
      const mappedErrors = mapRegisterError(message);
      if (mappedErrors) {
        const mappedFields = Object.keys(mappedErrors) as RegisterField[];
        setFieldErrors(mappedErrors);
        setTouchedFields((current) => touchFields(current, mappedFields));
        return;
      }
      setError(message);
    } finally {
      setIsSubmitting(false);
    }
  };

  const levelLabels = ["Beginner", "Elementary", "Intermediate", "Advanced", "Expert"];
  const emailError = getVisibleFieldError("email", fieldErrors, touchedFields);
  const verificationCodeError = getVisibleFieldError(
    "verificationCode",
    fieldErrors,
    touchedFields
  );
  const usernameError = getVisibleFieldError(
    "username",
    fieldErrors,
    touchedFields
  );
  const passwordError = getVisibleFieldError(
    "password",
    fieldErrors,
    touchedFields
  );
  const confirmPasswordError = getVisibleFieldError(
    "confirmPassword",
    fieldErrors,
    touchedFields
  );
  const acceptedUserNoticeError = getVisibleFieldError(
    "acceptedUserNotice",
    fieldErrors,
    touchedFields
  );

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-lg mx-auto py-8 px-4">
        <div className="bg-white rounded-lg shadow-md p-8">
          <h1 className="text-2xl font-bold text-center text-brand mb-2">
            Tell us about you
          </h1>
          <p className="text-center text-gray-500 mb-6">
            Create your account and set your skill levels
          </p>

          {error && (
            <div className="bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded mb-4">
              {error}
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
                  emailError ? getFieldErrorId("register", "email") : undefined
                }
              />
              {emailError && (
                <p
                  id={getFieldErrorId("register", "email")}
                  className="mt-1 text-sm text-red-600"
                >
                  {emailError}
                </p>
              )}
              {!emailError && emailHint && (
                <p className="mt-2 rounded border border-blue-300 bg-blue-50 px-2 py-1 text-xs text-blue-700">
                  {emailHint}
                </p>
              )}
            </div>

            {codeMessage && (
              <div className="rounded border border-green-300 bg-green-50 px-3 py-2 text-sm text-green-700">
                {codeMessage}
              </div>
            )}

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
                    ? getFieldErrorId("register", "verificationCode")
                    : undefined
                }
                maxLength={6}
                inputMode="numeric"
                pattern="\d{6}"
                placeholder="Enter 6-digit code"
              />
              {verificationCodeError && (
                <p
                  id={getFieldErrorId("register", "verificationCode")}
                  className="mt-1 text-sm text-red-600"
                >
                  {verificationCodeError}
                </p>
              )}
            </div>

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
                onBlur={() => handleBlur("username")}
                onChange={(event) =>
                  handleFieldChange("username", event.target.value, () => {
                    setUsername(event.target.value);
                  })
                }
                className={getTextInputClass(Boolean(usernameError))}
                aria-invalid={Boolean(usernameError)}
                aria-describedby={
                  usernameError
                    ? getFieldErrorId("register", "username")
                    : undefined
                }
                minLength={3}
                maxLength={50}
              />
              {usernameError && (
                <p
                  id={getFieldErrorId("register", "username")}
                  className="mt-1 text-sm text-red-600"
                >
                  {usernameError}
                </p>
              )}
            </div>

            <div>
              <label
                htmlFor="password"
                className="block text-sm font-medium text-gray-700 mb-1"
              >
                Password
              </label>
              <input
                type="password"
                id="password"
                value={password}
                onBlur={() => handleBlur("password")}
                onChange={(event) =>
                  handleFieldChange("password", event.target.value, () => {
                    setPassword(event.target.value);
                  })
                }
                className={getTextInputClass(Boolean(passwordError))}
                aria-invalid={Boolean(passwordError)}
                aria-describedby={
                  passwordError
                    ? getFieldErrorId("register", "password")
                    : undefined
                }
                minLength={8}
              />
              {passwordError && (
                <p
                  id={getFieldErrorId("register", "password")}
                  className="mt-1 text-sm text-red-600"
                >
                  {passwordError}
                </p>
              )}
            </div>

            <div>
              <label
                htmlFor="confirmPassword"
                className="block text-sm font-medium text-gray-700 mb-1"
              >
                Confirm Password
              </label>
              <input
                type="password"
                id="confirmPassword"
                value={confirmPassword}
                onBlur={() => handleBlur("confirmPassword")}
                onChange={(event) =>
                  handleFieldChange("confirmPassword", event.target.value, () => {
                    setConfirmPassword(event.target.value);
                  })
                }
                className={getTextInputClass(Boolean(confirmPasswordError))}
                aria-invalid={Boolean(confirmPasswordError)}
                aria-describedby={
                  confirmPasswordError
                    ? getFieldErrorId("register", "confirmPassword")
                    : undefined
                }
              />
              {confirmPasswordError && (
                <p
                  id={getFieldErrorId("register", "confirmPassword")}
                  className="mt-1 text-sm text-red-600"
                >
                  {confirmPasswordError}
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

            <div
              className={`rounded-md border px-4 py-3 ${
                acceptedUserNoticeError
                  ? "border-red-300 bg-red-50/70"
                  : "border-gray-200 bg-gray-50"
              }`}
            >
              <div className="flex items-start gap-3">
                <input
                  type="checkbox"
                  id="acceptedUserNotice"
                  checked={acceptedUserNotice}
                  onBlur={() => handleBlur("acceptedUserNotice")}
                  onChange={(event) =>
                    handleAcceptedUserNoticeChange(event.target.checked)
                  }
                  className="mt-1 h-4 w-4 rounded border-gray-300 text-accent focus:ring-accent"
                  aria-invalid={Boolean(acceptedUserNoticeError)}
                  aria-describedby={
                    acceptedUserNoticeError
                      ? getFieldErrorId("register", "acceptedUserNotice")
                      : undefined
                  }
                />
                <div className="space-y-2">
                  <div className="text-sm text-gray-700">
                    <label
                      htmlFor="acceptedUserNotice"
                      className="font-medium text-gray-900"
                    >
                      I have read and agree to the
                    </label>{" "}
                    <button
                      type="button"
                      onClick={() => setIsUserNoticeOpen(true)}
                      className="font-medium text-accent-dark hover:underline"
                    >
                      User Notice
                    </button>
                    .
                  </div>
                  <p className="text-xs text-gray-600">
                    Open the notice to review privacy, data retention, and
                    contact details.
                  </p>
                  {acceptedUserNoticeError && (
                    <p
                      id={getFieldErrorId("register", "acceptedUserNotice")}
                      className="text-sm text-red-600"
                    >
                      {acceptedUserNoticeError}
                    </p>
                  )}
                </div>
              </div>
            </div>

            <button
              type="submit"
              disabled={isSubmitting}
              className="w-full bg-brand text-white py-2 px-4 rounded-md hover:bg-brand-light focus:outline-none focus:ring-2 focus:ring-accent disabled:opacity-50"
            >
              {isSubmitting ? "Creating account..." : "Create Account"}
            </button>
          </form>

          <p className="mt-4 text-center text-sm text-gray-600">
            Already have an account?{" "}
            <Link to="/login" className="text-accent-dark hover:underline">
              Login
            </Link>
          </p>
          <p className="mt-2 text-center text-sm text-gray-600">
            Forgot your password?{" "}
            <Link to="/forgot-password" className="text-accent-dark hover:underline">
              Reset it here
            </Link>
          </p>
        </div>

        <UserNoticeDialog
          isOpen={isUserNoticeOpen}
          onClose={() => setIsUserNoticeOpen(false)}
        />
      </div>
    </div>
  );
}
