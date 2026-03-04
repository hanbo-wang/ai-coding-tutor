"""Verification functions for notebook exercises."""

import numpy as np
import math

_GREEN = "\033[92m"
_RED = "\033[91m"
_RESET = "\033[0m"


# ---------------------------------------------------------------------------
# Notebook 1 — Vectors and Matrices
# ---------------------------------------------------------------------------

def check_loop_matmul(fn):
    """Verify loop-based matrix multiplication."""
    _run_tests(fn, "Loop-based multiplication")


def check_vectorised_matmul(fn):
    """Verify vectorised matrix multiplication."""
    _run_tests(fn, "Vectorised multiplication")


def _run_tests(fn, label):
    """Run test cases against the student's function."""
    np.random.seed(42)
    cases = [
        (np.array([[1]]), np.array([[2]])),
        (np.array([[1, 2], [3, 4]]), np.array([[5, 6], [7, 8]])),
        (np.random.randint(-5, 6, (3, 4)), np.random.randint(-5, 6, (4, 2))),
        (np.zeros((2, 3)), np.ones((3, 2))),
        (np.random.randint(-10, 11, (5, 3)), np.random.randint(-10, 11, (3, 4))),
    ]

    for i, (A, B) in enumerate(cases, 1):
        try:
            result = fn(A, B)
            expected = A @ B
            if not np.allclose(result, expected, atol=1e-8):
                print(f"{_RED}{label} — Test {i} failed.{_RESET}")
                print(f"  A shape: {A.shape},  B shape: {B.shape}")
                print(f"  Expected (first row): {expected[0]}")
                print(f"  Got      (first row): {result[0]}")
                return
        except Exception as e:
            print(f"{_RED}{label} — Test {i} raised an error: {e}{_RESET}")
            return

    print(f"{_GREEN}{label} — All tests passed.{_RESET}")


# ---------------------------------------------------------------------------
# Notebook 2 — Core Concepts and Applications
# ---------------------------------------------------------------------------

def _mod_inverse_matrix(K, mod=26):
    """Compute modular inverse of matrix K (internal helper)."""
    det = int(round(np.linalg.det(K)))
    det_mod = det % mod
    det_inv = pow(det_mod, -1, mod)
    adjugate = np.round(det * np.linalg.inv(K)).astype(int)
    return (det_inv * adjugate) % mod


def check_hill_encrypt(fn):
    """Verify Hill cipher encryption."""
    label = "Hill encryption"
    cases = [
        (np.array([7, 4]), np.array([[3, 3], [2, 5]])),       # HE
        (np.array([11, 11]), np.array([[3, 3], [2, 5]])),     # LL
        (np.array([14, 23]), np.array([[3, 3], [2, 5]])),     # OX
        (np.array([0, 1, 2]), np.array([[6, 24, 1], [13, 16, 10], [20, 17, 15]])),
    ]
    for i, (plain, K) in enumerate(cases, 1):
        try:
            result = fn(plain, K)
            expected = (K @ plain) % 26
            if not np.array_equal(np.round(result).astype(int) % 26, expected):
                print(f"{_RED}{label} — Test {i} failed.{_RESET}")
                print(f"  Expected: {expected}")
                print(f"  Got:      {np.round(result).astype(int) % 26}")
                return
        except Exception as e:
            print(f"{_RED}{label} — Test {i} raised an error: {e}{_RESET}")
            return
    print(f"{_GREEN}{label} — All tests passed.{_RESET}")


def check_valid_key(fn):
    """Verify Hill cipher key validation."""
    label = "Key validation"
    cases = [
        (np.array([[3, 3], [2, 5]]), True),    # det=9, gcd(9,26)=1
        (np.array([[2, 4], [6, 8]]), False),   # det=-8, gcd(18,26)=2
        (np.array([[1, 2], [2, 4]]), False),    # singular
        (np.array([[6, 24, 1], [13, 16, 10], [20, 17, 15]]), True),  # 3x3 valid
        (np.array([[1, 0], [0, 13]]), False),   # det=13, gcd(13,26)=13
    ]
    for i, (K, expected) in enumerate(cases, 1):
        try:
            result = fn(K)
            if result != expected:
                print(f"{_RED}{label} — Test {i} failed.{_RESET}")
                det = int(round(np.linalg.det(K))) % 26
                print(f"  det(K) mod 26 = {det}, gcd = {math.gcd(det, 26)}")
                print(f"  Expected: {expected}, Got: {result}")
                return
        except Exception as e:
            print(f"{_RED}{label} — Test {i} raised an error: {e}{_RESET}")
            return
    print(f"{_GREEN}{label} — All tests passed.{_RESET}")


def check_hill_decrypt(fn):
    """Verify Hill cipher decryption."""
    label = "Hill decryption"
    K = np.array([[3, 3], [2, 5]])
    plain_vectors = [
        np.array([7, 4]),    # HE
        np.array([11, 11]),  # LL
        np.array([14, 23]),  # OX
    ]
    for i, plain in enumerate(plain_vectors, 1):
        cipher = (K @ plain) % 26
        try:
            result = fn(cipher, K)
            if not np.array_equal(np.round(result).astype(int) % 26, plain):
                print(f"{_RED}{label} — Test {i} failed.{_RESET}")
                print(f"  Cipher: {cipher}, Expected plain: {plain}")
                print(f"  Got: {np.round(result).astype(int) % 26}")
                return
        except Exception as e:
            print(f"{_RED}{label} — Test {i} raised an error: {e}{_RESET}")
            return
    print(f"{_GREEN}{label} — All tests passed.{_RESET}")


def _build_test_google_matrix():
    """Build a fixed Google matrix for PageRank tests."""
    # 6-node graph: A->B,C  B->C  C->A  D->C  E->C,D  F->D,E
    adj = np.zeros((6, 6))
    adj[1, 0] = 1; adj[2, 0] = 1   # A links to B, C
    adj[2, 1] = 1                    # B links to C
    adj[0, 2] = 1                    # C links to A
    adj[2, 3] = 1                    # D links to C
    adj[2, 4] = 1; adj[3, 4] = 1   # E links to C, D
    adj[3, 5] = 1; adj[4, 5] = 1   # F links to D, E
    # Column-normalise
    col_sums = adj.sum(axis=0)
    col_sums[col_sums == 0] = 1
    M = adj / col_sums
    d = 0.85
    n = 6
    G = d * M + (1 - d) / n * np.ones((n, n))
    return G


def check_pagerank(fn):
    """Verify eigenvalue-based PageRank computation."""
    label = "PageRank (eigenvalue)"
    G = _build_test_google_matrix()
    try:
        result = fn(G)
        if not np.all(result > 0):
            print(f"{_RED}{label} — Failed: some ranks are not positive.{_RESET}")
            return
        if not np.isclose(result.sum(), 1.0, atol=1e-6):
            print(f"{_RED}{label} — Failed: ranks do not sum to 1.{_RESET}")
            print(f"  Sum: {result.sum()}")
            return
        # Verify against known solution via power iteration
        r = np.ones(6) / 6
        for _ in range(200):
            r = G @ r
        if not np.allclose(result, r, atol=1e-4):
            print(f"{_RED}{label} — Failed: ranks do not match expected values.{_RESET}")
            print(f"  Expected: {np.round(r, 4)}")
            print(f"  Got:      {np.round(result, 4)}")
            return
    except Exception as e:
        print(f"{_RED}{label} — Raised an error: {e}{_RESET}")
        return
    print(f"{_GREEN}{label} — All tests passed.{_RESET}")


def check_power_iteration(fn):
    """Verify power-iteration PageRank computation."""
    label = "PageRank (power iteration)"
    G = _build_test_google_matrix()
    try:
        result = fn(G)
        # Reference via many iterations
        r = np.ones(6) / 6
        for _ in range(200):
            r = G @ r
        if not np.allclose(result, r, atol=1e-4):
            print(f"{_RED}{label} — Failed: did not converge to expected ranks.{_RESET}")
            print(f"  Expected: {np.round(r, 4)}")
            print(f"  Got:      {np.round(result, 4)}")
            return
    except Exception as e:
        print(f"{_RED}{label} — Raised an error: {e}{_RESET}")
        return
    print(f"{_GREEN}{label} — All tests passed.{_RESET}")
