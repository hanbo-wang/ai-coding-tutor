import { useState, FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "./useAuth";

export function RegisterPage() {
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [programmingLevel, setProgrammingLevel] = useState(3);
  const [mathsLevel, setMathsLevel] = useState(3);
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const { register } = useAuth();
  const navigate = useNavigate();

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");

    if (password !== confirmPassword) {
      setError("Passwords do not match");
      return;
    }

    if (password.length < 8) {
      setError("Password must be at least 8 characters");
      return;
    }

    setIsSubmitting(true);

    try {
      await register({
        email,
        username,
        password,
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
    <div className="max-w-lg mx-auto">
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
              onChange={(e) => setEmail(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-accent"
              required
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
      </div>
    </div>
  );
}
