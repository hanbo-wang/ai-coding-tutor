import { FormEvent, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import {
  FieldErrors,
  TouchedFields,
  getFieldErrorId,
  getTextInputClass,
  getVisibleFieldError,
  hasAnyFieldError,
  isValidEmail,
  touchFields,
} from "../forms/fieldValidation";
import { useAuth } from "./useAuth";
import { resolveAuthRedirectTarget } from "./redirect";

type LoginField = "email" | "password";

interface LoginValues {
  email: string;
  password: string;
}

const loginFields: readonly LoginField[] = ["email", "password"];

function validateLoginValues(values: LoginValues): FieldErrors<LoginField> {
  const errors: FieldErrors<LoginField> = {};
  const normalisedEmail = values.email.trim();

  if (!normalisedEmail) {
    errors.email = "Please enter your email first.";
  } else if (!isValidEmail(normalisedEmail)) {
    errors.email = "Please enter a valid email address.";
  }

  if (!values.password) {
    errors.password = "Please enter your password.";
  }

  return errors;
}

function mapLoginError(message: string): FieldErrors<LoginField> | null {
  if (message === "Invalid email or password") {
    return {
      email: message,
      password: message,
    };
  }
  return null;
}

export function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [fieldErrors, setFieldErrors] = useState<FieldErrors<LoginField>>({});
  const [touchedFields, setTouchedFields] = useState<TouchedFields<LoginField>>(
    {}
  );
  const [isSubmitting, setIsSubmitting] = useState(false);
  const { login } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();

  const syncValidation = (nextValues: LoginValues) => {
    setFieldErrors(validateLoginValues(nextValues));
  };

  const handleBlur = (field: LoginField) => {
    setTouchedFields((current) => touchFields(current, [field]));
    syncValidation({ email, password });
  };

  const handleEmailChange = (nextEmail: string) => {
    setEmail(nextEmail);
    setError("");
    if (touchedFields.email || hasAnyFieldError(fieldErrors)) {
      syncValidation({ email: nextEmail, password });
    }
  };

  const handlePasswordChange = (nextPassword: string) => {
    setPassword(nextPassword);
    setError("");
    if (touchedFields.password || hasAnyFieldError(fieldErrors)) {
      syncValidation({ email, password: nextPassword });
    }
  };

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setError("");
    const nextValues = { email, password };
    const nextErrors = validateLoginValues(nextValues);
    setFieldErrors(nextErrors);
    setTouchedFields((current) => touchFields(current, loginFields));
    if (hasAnyFieldError(nextErrors)) {
      return;
    }

    setIsSubmitting(true);

    try {
      await login({ email: email.trim(), password });
      navigate(resolveAuthRedirectTarget(location.state), { replace: true });
    } catch (err) {
      const message = err instanceof Error ? err.message : "Login failed.";
      const mappedErrors = mapLoginError(message);
      if (mappedErrors) {
        setFieldErrors(mappedErrors);
        setTouchedFields((current) => touchFields(current, loginFields));
        return;
      }
      setError(message);
    } finally {
      setIsSubmitting(false);
    }
  };

  const emailError = getVisibleFieldError("email", fieldErrors, touchedFields);
  const passwordError = getVisibleFieldError(
    "password",
    fieldErrors,
    touchedFields
  );

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-md mx-auto py-8 px-4">
        <div className="bg-white rounded-lg shadow-md p-8">
          <h1 className="text-2xl font-bold text-center text-brand mb-6">Login</h1>

          {error && (
            <div className="bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded mb-4">
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} noValidate className="space-y-4">
            <div>
              <label
                htmlFor="email"
                className="block text-sm font-medium text-gray-700 mb-1"
              >
                Email
              </label>
              <input
                type="email"
                id="email"
                value={email}
                onBlur={() => handleBlur("email")}
                onChange={(event) => handleEmailChange(event.target.value)}
                className={getTextInputClass(Boolean(emailError))}
                aria-invalid={Boolean(emailError)}
                aria-describedby={
                  emailError ? getFieldErrorId("login", "email") : undefined
                }
              />
              {emailError && (
                <p
                  id={getFieldErrorId("login", "email")}
                  className="mt-1 text-sm text-red-600"
                >
                  {emailError}
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
                onChange={(event) => handlePasswordChange(event.target.value)}
                className={getTextInputClass(Boolean(passwordError))}
                aria-invalid={Boolean(passwordError)}
                aria-describedby={
                  passwordError
                    ? getFieldErrorId("login", "password")
                    : undefined
                }
              />
              {passwordError && (
                <p
                  id={getFieldErrorId("login", "password")}
                  className="mt-1 text-sm text-red-600"
                >
                  {passwordError}
                </p>
              )}
            </div>

            <div className="text-right">
              <Link
                to="/forgot-password"
                state={location.state}
                className="text-sm text-accent-dark hover:underline"
              >
                Forgot password?
              </Link>
            </div>

            <button
              type="submit"
              disabled={isSubmitting}
              className="w-full bg-brand text-white py-2 px-4 rounded-md hover:bg-brand-light focus:outline-none focus:ring-2 focus:ring-accent disabled:opacity-50"
            >
              {isSubmitting ? "Logging in..." : "Login"}
            </button>
          </form>

          <p className="mt-4 text-center text-sm text-gray-600">
            Don't have an account?{" "}
            <Link
              to="/register"
              state={location.state}
              className="text-accent-dark hover:underline"
            >
              Register
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
