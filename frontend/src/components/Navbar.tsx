import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/useAuth";

export function Navbar() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const handleLogout = async () => {
    await logout();
    navigate("/login");
  };

  return (
    <nav className="bg-brand shadow-md">
      <div className="container mx-auto px-4">
        <div className="flex justify-between items-center h-16">
          <Link to="/" className="text-xl font-bold text-accent-light">
            Guided Cursor
          </Link>

          <div className="flex items-center space-x-4">
            {user ? (
              <>
                <Link
                  to="/chat"
                  className="text-gray-200 hover:text-accent-light"
                >
                  Chat
                </Link>
                <Link
                  to="/my-notebooks"
                  className="text-gray-200 hover:text-accent-light"
                >
                  My Notebooks
                </Link>
                <Link
                  to="/learning-hub"
                  className="text-gray-200 hover:text-accent-light"
                >
                  Learning Hub
                </Link>
                {user.is_admin && (
                  <Link
                    to="/admin"
                    className="text-gray-200 hover:text-accent-light"
                  >
                    Admin
                  </Link>
                )}
                <Link
                  to="/profile"
                  className="text-gray-200 hover:text-accent-light"
                >
                  Profile
                </Link>
                <button
                  onClick={handleLogout}
                  className="bg-accent text-brand px-4 py-2 rounded-md hover:bg-accent-dark"
                >
                  Logout
                </button>
              </>
            ) : (
              <>
                <Link
                  to="/login"
                  className="text-gray-200 hover:text-accent-light"
                >
                  Login
                </Link>
                <Link
                  to="/register"
                  className="bg-accent text-brand px-4 py-2 rounded-md hover:bg-accent-dark"
                >
                  Register
                </Link>
              </>
            )}
          </div>
        </div>
      </div>
    </nav>
  );
}
