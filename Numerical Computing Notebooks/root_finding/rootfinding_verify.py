"""Verification functions for notebook exercises."""

import numpy as np

_GREEN = "\033[92m"
_RED = "\033[91m"
_RESET = "\033[0m"


# ---------------------------------------------------------------------------
# Newton's method check
# ---------------------------------------------------------------------------

def check_newton_method(fn):
    """Verify the student's Newton's method implementation."""
    cases = [
        (
            "x^2 - 4",
            lambda x: x**2 - 4,
            lambda x: 2 * x,
            3.0,
            2.0,
        ),
        (
            "cos(x) - x",
            lambda x: np.cos(x) - x,
            lambda x: -np.sin(x) - 1,
            1.0,
            0.7390851332151607,
        ),
        (
            "x^3 - 2x - 5",
            lambda x: x**3 - 2 * x - 5,
            lambda x: 3 * x**2 - 2,
            2.0,
            2.0945514815423265,
        ),
        (
            "exp(-x) - x",
            lambda x: np.exp(-x) - x,
            lambda x: -np.exp(-x) - 1,
            0.5,
            0.5671432904097838,
        ),
    ]

    for i, (name, g, dg, x0, x_true) in enumerate(cases, 1):
        try:
            x, history = fn(g, dg, x0)

            if not isinstance(history, list):
                print(f"{_RED}Newton's method — Test {i} ({name}) failed.{_RESET}")
                print("  history should be a list.")
                return

            if len(history) < 2:
                print(f"{_RED}Newton's method — Test {i} ({name}) failed.{_RESET}")
                print(f"  history has {len(history)} entries (expected at least 2).")
                return

            if abs(g(x)) > 1e-8:
                print(f"{_RED}Newton's method — Test {i} ({name}) failed.{_RESET}")
                print(f"  |g(x)| = {abs(g(x)):.2e} (should be < 1e-8).")
                print(f"  x = {x}, expected root near {x_true:.10f}.")
                return

        except Exception as e:
            print(f"{_RED}Newton's method — Test {i} ({name}) raised an error: {e}{_RESET}")
            return

    print(f"{_GREEN}Newton's method — All tests passed.{_RESET}")


# ---------------------------------------------------------------------------
# Secant method check
# ---------------------------------------------------------------------------

def check_secant_method(fn):
    """Verify the student's Secant method implementation."""
    cases = [
        (
            "x^2 - 4",
            lambda x: x**2 - 4,
            1.0,
            3.0,
            2.0,
        ),
        (
            "cos(x) - x",
            lambda x: np.cos(x) - x,
            0.0,
            1.0,
            0.7390851332151607,
        ),
        (
            "x^3 - 2x - 5",
            lambda x: x**3 - 2 * x - 5,
            2.0,
            3.0,
            2.0945514815423265,
        ),
        (
            "exp(-x) - x",
            lambda x: np.exp(-x) - x,
            0.0,
            1.0,
            0.5671432904097838,
        ),
    ]

    for i, (name, g, x0, x1, x_true) in enumerate(cases, 1):
        try:
            x, history = fn(g, x0, x1)

            if not isinstance(history, list):
                print(f"{_RED}Secant method — Test {i} ({name}) failed.{_RESET}")
                print("  history should be a list.")
                return

            if len(history) < 3:
                print(f"{_RED}Secant method — Test {i} ({name}) failed.{_RESET}")
                print(f"  history has {len(history)} entries (expected at least 3).")
                return

            if abs(g(x)) > 1e-8:
                print(f"{_RED}Secant method — Test {i} ({name}) failed.{_RESET}")
                print(f"  |g(x)| = {abs(g(x)):.2e} (should be < 1e-8).")
                print(f"  x = {x}, expected root near {x_true:.10f}.")
                return

        except Exception as e:
            print(f"{_RED}Secant method — Test {i} ({name}) raised an error: {e}{_RESET}")
            return

    print(f"{_GREEN}Secant method — All tests passed.{_RESET}")
