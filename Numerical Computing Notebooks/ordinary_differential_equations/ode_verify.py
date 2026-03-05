"""Verification functions for notebook exercises."""

import numpy as np

_GREEN = "\033[92m"
_RED = "\033[91m"
_RESET = "\033[0m"


# ---------------------------------------------------------------------------
# Reference analytical solutions
# ---------------------------------------------------------------------------

def _exact_decay(t):
    """y' = -2y, y(0)=1  =>  y = exp(-2t)."""
    return np.exp(-2 * t)


def _exact_linear(t):
    """y' = t - y, y(0)=0  =>  y = t - 1 + exp(-t)."""
    return t - 1 + np.exp(-t)


# ---------------------------------------------------------------------------
# Internal test runner
# ---------------------------------------------------------------------------

def _run_ode_tests(fn, label, is_second_order=False):
    """Run standard test cases against the student's ODE solver."""
    f_decay = lambda t, y: -2 * y
    f_linear = lambda t, y: t - y

    cases = [
        ("decay (h=0.1)", f_decay, (0, 2), 1.0, 0.1, _exact_decay),
        ("decay (h=0.01)", f_decay, (0, 1), 1.0, 0.01, _exact_decay),
        ("linear (h=0.1)", f_linear, (0, 2), 0.0, 0.1, _exact_linear),
        ("linear (h=0.05)", f_linear, (0, 1), 0.0, 0.05, _exact_linear),
    ]

    for i, (name, f, t_span, y0, h, exact) in enumerate(cases, 1):
        try:
            t, y = fn(f, t_span, y0, h)

            if len(t) != len(y):
                print(f"{_RED}{label} — Test {i} ({name}) failed.{_RESET}")
                print(f"  t has {len(t)} points but y has {len(y)} points.")
                return

            y_true = exact(t)
            max_err = np.max(np.abs(y - y_true))
            tol = 0.05 if is_second_order else 0.5
            if h <= 0.01:
                tol = min(tol, 0.05)

            if max_err > tol:
                print(f"{_RED}{label} — Test {i} ({name}) failed.{_RESET}")
                print(f"  Max error: {max_err:.6f} (tolerance: {tol})")
                print(f"  y[-1] expected: {y_true[-1]:.6f}, got: {y[-1]:.6f}")
                return

        except Exception as e:
            print(f"{_RED}{label} — Test {i} ({name}) raised an error: {e}{_RESET}")
            return

    print(f"{_GREEN}{label} — All tests passed.{_RESET}")


# ---------------------------------------------------------------------------
# Public check functions
# ---------------------------------------------------------------------------

def check_forward_euler(fn):
    """Verify the student's Forward Euler implementation."""
    _run_ode_tests(fn, "Forward Euler")


def check_rk2_heun(fn):
    """Verify the student's RK2 (Heun) implementation."""
    _run_ode_tests(fn, "RK2 (Heun)", is_second_order=True)


def check_rk2_midpoint(fn):
    """Verify the student's RK2 (Midpoint) implementation."""
    _run_ode_tests(fn, "RK2 (Midpoint)", is_second_order=True)


# ---------------------------------------------------------------------------
# RK4 scalar check
# ---------------------------------------------------------------------------

def check_rk4(fn):
    """Verify the student's scalar RK4 implementation."""
    f_decay = lambda t, y: -2 * y
    f_linear = lambda t, y: t - y

    cases = [
        ("decay (h=0.1)", f_decay, (0, 2), 1.0, 0.1, _exact_decay),
        ("decay (h=0.5)", f_decay, (0, 3), 1.0, 0.5, _exact_decay),
        ("linear (h=0.1)", f_linear, (0, 2), 0.0, 0.1, _exact_linear),
        ("linear (h=0.25)", f_linear, (0, 2), 0.0, 0.25, _exact_linear),
    ]

    for i, (name, f, t_span, y0, h, exact) in enumerate(cases, 1):
        try:
            t, y = fn(f, t_span, y0, h)

            if len(t) != len(y):
                print(f"{_RED}RK4 — Test {i} ({name}) failed.{_RESET}")
                print(f"  t has {len(t)} points but y has {len(y)} points.")
                return

            y_true = exact(t)
            max_err = np.max(np.abs(y - y_true))
            tol = 0.01 if h >= 0.25 else 1e-3
            if max_err > tol:
                print(f"{_RED}RK4 — Test {i} ({name}) failed.{_RESET}")
                print(f"  Max error: {max_err:.8f} (tolerance: {tol})")
                print(f"  y[-1] expected: {y_true[-1]:.8f}, got: {y[-1]:.8f}")
                return

        except Exception as e:
            print(f"{_RED}RK4 — Test {i} ({name}) raised an error: {e}{_RESET}")
            return

    print(f"{_GREEN}RK4 — All tests passed.{_RESET}")


# ---------------------------------------------------------------------------
# RK4 system check
# ---------------------------------------------------------------------------

def _exact_2d_linear(t):
    """Exact solution for y' = [0 1; -1 0] y, y(0) = [1, 0] => [cos t, -sin t]."""
    return np.column_stack([np.cos(t), -np.sin(t)])


def check_rk4_system(fn):
    """Verify the student's RK4 system (vector) implementation."""
    # Simple harmonic oscillator: y'' = -y => y1' = y2, y2' = -y1
    f_sho = lambda t, y: np.array([y[1], -y[0]])
    y0_sho = np.array([1.0, 0.0])

    cases = [
        ("harmonic (h=0.1)", f_sho, (0, 2 * np.pi), y0_sho, 0.1),
        ("harmonic (h=0.05)", f_sho, (0, 4 * np.pi), y0_sho, 0.05),
    ]

    for i, (name, f, t_span, y0, h) in enumerate(cases, 1):
        try:
            t, Y = fn(f, t_span, y0, h)

            if Y.shape != (len(t), len(y0)):
                print(f"{_RED}RK4 System — Test {i} ({name}) failed.{_RESET}")
                print(f"  Expected Y shape ({len(t)}, {len(y0)}), got {Y.shape}.")
                return

            Y_true = _exact_2d_linear(t)
            max_err = np.max(np.abs(Y - Y_true))
            tol = 1e-3
            if max_err > tol:
                print(f"{_RED}RK4 System — Test {i} ({name}) failed.{_RESET}")
                print(f"  Max error: {max_err:.8f} (tolerance: {tol})")
                return

        except Exception as e:
            print(f"{_RED}RK4 System — Test {i} ({name}) raised an error: {e}{_RESET}")
            return

    print(f"{_GREEN}RK4 System — All tests passed.{_RESET}")


# ---------------------------------------------------------------------------
# Van der Pol right-hand side check
# ---------------------------------------------------------------------------

def check_van_der_pol(fn):
    """Verify the student's Van der Pol right-hand side function."""
    test_cases = [
        # (state, mu, expected_output)
        (np.array([0.0, 0.0]), 1.0, np.array([0.0, 0.0])),
        (np.array([1.0, 0.0]), 1.0, np.array([0.0, -1.0])),
        (np.array([0.0, 1.0]), 1.0, np.array([1.0, 1.0])),
        (np.array([2.0, 1.0]), 3.0, np.array([1.0, -11.0])),
    ]

    for i, (state, mu, expected) in enumerate(test_cases, 1):
        try:
            result = fn(0, state, mu)
            result = np.asarray(result, dtype=float)

            if result.shape != expected.shape:
                print(f"{_RED}Van der Pol — Test {i} failed.{_RESET}")
                print(f"  Expected shape {expected.shape}, got {result.shape}.")
                return

            if not np.allclose(result, expected, atol=1e-10):
                print(f"{_RED}Van der Pol — Test {i} failed.{_RESET}")
                print(f"  state={state}, mu={mu}")
                print(f"  Expected: {expected}, Got: {result}")
                return

        except Exception as e:
            print(f"{_RED}Van der Pol — Test {i} raised an error: {e}{_RESET}")
            return

    print(f"{_GREEN}Van der Pol — All tests passed.{_RESET}")
