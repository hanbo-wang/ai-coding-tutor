"""Verification functions for notebook exercises."""

import numpy as np

_GREEN = "\033[92m"
_RED = "\033[91m"
_RESET = "\033[0m"


# ---------------------------------------------------------------------------
# Naive DFT check
# ---------------------------------------------------------------------------

def check_naive_dft(fn):
    """Verify the student's naive DFT implementation."""
    cases = [
        (
            "impulse [1, 0, 0, 0]",
            np.array([1, 0, 0, 0], dtype=complex),
        ),
        (
            "DC signal [1, 1, 1, 1]",
            np.array([1, 1, 1, 1], dtype=complex),
        ),
        (
            "cosine (N=8, k=2)",
            np.cos(2 * np.pi * 2 * np.arange(8) / 8),
        ),
        (
            "random signal (N=16)",
            np.random.RandomState(42).randn(16),
        ),
    ]

    for i, (name, x) in enumerate(cases, 1):
        try:
            result = fn(x)
            expected = np.fft.fft(x)

            if not isinstance(result, np.ndarray):
                print(f"{_RED}Naive DFT — Test {i} ({name}) failed.{_RESET}")
                print("  Return value should be a NumPy array.")
                return

            if len(result) != len(x):
                print(f"{_RED}Naive DFT — Test {i} ({name}) failed.{_RESET}")
                print(f"  Output length is {len(result)} (expected {len(x)}).")
                return

            if not np.allclose(result, expected, atol=1e-8):
                print(f"{_RED}Naive DFT — Test {i} ({name}) failed.{_RESET}")
                print(f"  Max error: {np.max(np.abs(result - expected)):.2e}")
                return

        except Exception as e:
            print(f"{_RED}Naive DFT — Test {i} ({name}) raised an error: {e}{_RESET}")
            return

    print(f"{_GREEN}Naive DFT — All tests passed.{_RESET}")


# ---------------------------------------------------------------------------
# Noisy spectrum check
# ---------------------------------------------------------------------------

def check_noisy_spectrum(freqs_n, X_clean, X_noisy, N_noisy, fs_noisy):
    """Verify the student's noisy spectrum computation."""
    try:
        # Rebuild reference signals
        t_ref = np.arange(N_noisy) / fs_noisy
        clean_ref = (1.0 * np.sin(2 * np.pi * 50 * t_ref)
                   + 0.5 * np.sin(2 * np.pi * 120 * t_ref)
                   + 0.3 * np.sin(2 * np.pi * 300 * t_ref))
        np.random.seed(0)
        noisy_ref = clean_ref + 1.5 * np.random.randn(N_noisy)

        expected_freqs = np.fft.rfftfreq(N_noisy, d=1/fs_noisy)
        expected_clean = np.abs(np.fft.rfft(clean_ref))
        expected_noisy = np.abs(np.fft.rfft(noisy_ref))
        expected_len = N_noisy // 2 + 1

        # Check freqs_n
        if not isinstance(freqs_n, np.ndarray):
            print(f"{_RED}Noisy spectrum — freqs_n should be a NumPy array.{_RESET}")
            return
        if len(freqs_n) != expected_len:
            print(f"{_RED}Noisy spectrum — freqs_n length is {len(freqs_n)} (expected {expected_len}).{_RESET}")
            return
        if not np.allclose(freqs_n, expected_freqs, atol=1e-8):
            print(f"{_RED}Noisy spectrum — freqs_n values do not match expected.{_RESET}")
            return

        # Check X_clean
        if not isinstance(X_clean, np.ndarray):
            print(f"{_RED}Noisy spectrum — X_clean should be a NumPy array.{_RESET}")
            return
        if len(X_clean) != expected_len:
            print(f"{_RED}Noisy spectrum — X_clean length is {len(X_clean)} (expected {expected_len}).{_RESET}")
            return
        if not np.allclose(X_clean, expected_clean, atol=1e-8):
            print(f"{_RED}Noisy spectrum — X_clean values do not match expected.{_RESET}")
            return

        # Check X_noisy
        if not isinstance(X_noisy, np.ndarray):
            print(f"{_RED}Noisy spectrum — X_noisy should be a NumPy array.{_RESET}")
            return
        if len(X_noisy) != expected_len:
            print(f"{_RED}Noisy spectrum — X_noisy length is {len(X_noisy)} (expected {expected_len}).{_RESET}")
            return
        if not np.allclose(X_noisy, expected_noisy, atol=1e-8):
            print(f"{_RED}Noisy spectrum — X_noisy values do not match expected.{_RESET}")
            return

    except Exception as e:
        print(f"{_RED}Noisy spectrum — raised an error: {e}{_RESET}")
        return

    print(f"{_GREEN}Noisy spectrum — All checks passed.{_RESET}")
