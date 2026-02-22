import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/useAuth";

export function Navbar() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  useEffect(() => {
    setMobileMenuOpen(false);
  }, [location.pathname]);

  const handleLogout = async () => {
    setMobileMenuOpen(false);
    await logout();
    navigate("/login");
  };

  const isRouteActive = (path: string) => {
    if (path === "/chat") return location.pathname === "/chat";
    if (path === "/my-notebooks") {
      return (
        location.pathname === "/my-notebooks" ||
        location.pathname.startsWith("/notebook/")
      );
    }
    if (path === "/learning-hub") {
      return (
        location.pathname === "/learning-hub" ||
        location.pathname.startsWith("/zones/") ||
        location.pathname.startsWith("/zone-notebook/")
      );
    }
    if (path === "/profile") {
      return (
        location.pathname === "/profile" ||
        location.pathname === "/change-password"
      );
    }
    return location.pathname === path;
  };

  const desktopLinkClass = (path: string) =>
    `rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
      isRouteActive(path)
        ? "bg-white/8 text-white ring-1 ring-inset ring-white/20"
        : "text-gray-200 hover:bg-white/10 hover:text-white"
    }`;

  const mobileLinkClass = (path: string) =>
    `rounded-lg px-3 py-2 text-sm transition-colors ${
      isRouteActive(path)
        ? "bg-white/8 text-white ring-1 ring-inset ring-white/20 font-medium"
        : "text-gray-200 hover:bg-white/10 hover:text-white"
    }`;

  const navPanelClass =
    "rounded-xl border border-white/10 bg-white/5 shadow-sm backdrop-blur";
  const primaryActionClass =
    "rounded-lg bg-accent px-4 py-2 text-sm font-medium text-brand transition-colors hover:bg-accent-dark";

  return (
    <nav className="border-b border-white/10 bg-brand shadow-md">
      <div className="container mx-auto px-4">
        <div className="flex justify-between items-center h-16 gap-4">
          <Link to="/" className="text-xl font-bold text-white shrink-0">
            Guided Cursor
          </Link>

          <div className={`hidden lg:flex items-center gap-1 p-1.5 ${navPanelClass}`}>
            {user ? (
              <>
                <Link to="/chat" className={desktopLinkClass("/chat")}>
                  Chat
                </Link>
                <Link
                  to="/my-notebooks"
                  className={desktopLinkClass("/my-notebooks")}
                >
                  My Notebooks
                </Link>
                <Link
                  to="/learning-hub"
                  className={desktopLinkClass("/learning-hub")}
                >
                  Learning Hub
                </Link>
                {user.is_admin && (
                  <Link to="/admin" className={desktopLinkClass("/admin")}>
                    Admin
                  </Link>
                )}
                <Link to="/profile" className={desktopLinkClass("/profile")}>
                  Profile
                </Link>
                <button
                  type="button"
                  onClick={handleLogout}
                  className={primaryActionClass}
                >
                  Logout
                </button>
              </>
            ) : (
              <>
                <Link to="/login" className={desktopLinkClass("/login")}>
                  Login
                </Link>
                <Link
                  to="/register"
                  className={`${primaryActionClass} ${
                    isRouteActive("/register")
                      ? "ring-2 ring-inset ring-white/15"
                      : ""
                  }`}
                >
                  Register
                </Link>
              </>
            )}
          </div>

          <button
            type="button"
            onClick={() => setMobileMenuOpen((open) => !open)}
            className="lg:hidden rounded-lg border border-white/10 bg-white/5 p-2 text-gray-200 hover:bg-white/10 hover:text-white focus:outline-none focus:ring-2 focus:ring-accent"
            aria-label={mobileMenuOpen ? "Close menu" : "Open menu"}
            aria-expanded={mobileMenuOpen}
            aria-controls="mobile-nav"
          >
            <svg
              className="h-5 w-5"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              {mobileMenuOpen ? (
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M6 18L18 6M6 6l12 12"
                />
              ) : (
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M4 6h16M4 12h16M4 18h16"
                />
              )}
            </svg>
          </button>
        </div>

        <div
          id="mobile-nav"
          className={`${mobileMenuOpen ? "block" : "hidden"} lg:hidden py-3`}
        >
          <div className={`${navPanelClass} p-2 shadow-lg`}>
            <div className="flex flex-col gap-1">
              {user ? (
                <>
                  <Link
                    to="/chat"
                    className={mobileLinkClass("/chat")}
                  >
                    Chat
                  </Link>
                  <Link
                    to="/my-notebooks"
                    className={mobileLinkClass("/my-notebooks")}
                  >
                    My Notebooks
                  </Link>
                  <Link
                    to="/learning-hub"
                    className={mobileLinkClass("/learning-hub")}
                  >
                    Learning Hub
                  </Link>
                  {user.is_admin && (
                    <Link
                      to="/admin"
                      className={mobileLinkClass("/admin")}
                    >
                      Admin
                    </Link>
                  )}
                  <Link
                    to="/profile"
                    className={mobileLinkClass("/profile")}
                  >
                    Profile
                  </Link>
                  <div className="my-1 h-px bg-gray-200" />
                  <button
                    type="button"
                    onClick={handleLogout}
                    className={`w-full text-left ${primaryActionClass}`}
                  >
                    Logout
                  </button>
                </>
              ) : (
                <>
                  <Link
                    to="/login"
                    className={mobileLinkClass("/login")}
                  >
                    Login
                  </Link>
                  <Link
                    to="/register"
                    className={`${primaryActionClass} ${
                      isRouteActive("/register")
                        ? "ring-2 ring-inset ring-white/15"
                        : ""
                    }`}
                  >
                    Register
                  </Link>
                </>
              )}
            </div>
          </div>
        </div>
      </div>
    </nav>
  );
}
