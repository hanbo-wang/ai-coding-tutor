import { useEffect, useState, FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "./useAuth";

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

function isValidEmail(value: string): boolean {
  return EMAIL_PATTERN.test(value);
}

export function RegisterPage() {
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [verificationCode, setVerificationCode] = useState("");
  const [codeMessage, setCodeMessage] = useState("");
  const [programmingLevel, setProgrammingLevel] = useState(3);
  const [mathsLevel, setMathsLevel] = useState(3);
  const [error, setError] = useState("");
  const [isSendingCode, setIsSendingCode] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [resendCooldown, setResendCooldown] = useState(0);
  const { register, sendRegisterCode } = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    if (resendCooldown <= 0) {
      return;
    }
    const timer = window.setInterval(() => {
      setResendCooldown((value) => (value > 0 ? value - 1 : 0));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [resendCooldown]);

  const handleSendCode = async () => {
    setError("");
    setCodeMessage("");
    const normalisedEmail = email.trim();
    const normalisedUsername = username.trim();

    if (!normalisedEmail) {
      setError("Please enter your email first");
      return;
    }
    if (!isValidEmail(normalisedEmail)) {
      setError("Please enter a valid email address.");
      return;
    }
    if (!normalisedUsername) {
      setError("Please enter your username first");
      return;
    }
    if (normalisedUsername.length < 3 || normalisedUsername.length > 50) {
      setError("Username must be between 3 and 50 characters.");
      return;
    }

    setIsSendingCode(true);
    try {
      await sendRegisterCode(normalisedEmail, normalisedUsername);
      setCodeMessage("Verification code sent. Please check your inbox.");
      setResendCooldown(60);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to send code");
    } finally {
      setIsSendingCode(false);
    }
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setCodeMessage("");
    const normalisedEmail = email.trim();
    const normalisedUsername = username.trim();

    if (!normalisedEmail) {
      setError("Please enter your email first");
      return;
    }
    if (!isValidEmail(normalisedEmail)) {
      setError("Please enter a valid email address.");
      return;
    }
    if (!normalisedUsername) {
      setError("Please enter a username");
      return;
    }
    if (normalisedUsername.length < 3 || normalisedUsername.length > 50) {
      setError("Username must be between 3 and 50 characters.");
      return;
    }

    if (password !== confirmPassword) {
      setError("Passwords do not match");
      return;
    }

    if (password.length < 8) {
      setError("Password must be at least 8 characters");
      return;
    }
    if (!/^\d{6}$/.test(verificationCode)) {
      setError("Please enter a valid 6-digit verification code");
      return;
    }

    setIsSubmitting(true);

    try {
      await register({
        email: normalisedEmail,
        username: normalisedUsername,
        password,
        verification_code: verificationCode,
        programming_level: programmingLevel,
        maths_level: mathsLevel,
      });
      navigate("/chat");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Registration failed");
    } finally {
      setIsSubmitting(false);
    }
  };

  const levelLabels = ["Beginner", "Elementary", "Intermediate", "Advanced", "Expert"];

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

          <form onSubmit={handleSubmit} className="space-y-4">
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
                onChange={(e) => setEmail(e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-accent"
                required
              />
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
                onChange={(e) =>
                  setVerificationCode(e.target.value.replace(/\D/g, "").slice(0, 6))
                }
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-accent"
                required
                maxLength={6}
                inputMode="numeric"
                pattern="\d{6}"
                placeholder="Enter 6-digit code"
              />
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
                onChange={(e) => setUsername(e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-accent"
                required
                minLength={3}
                maxLength={50}
              />
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
                onChange={(e) => setPassword(e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-accent"
                required
                minLength={8}
              />
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
                onChange={(e) => setConfirmPassword(e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-accent"
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
      </div>
    </div>
  );
}
