"""Collapsible hint boxes for notebook exercises."""

from IPython.display import display, HTML

_STYLE = (
    "margin: 8px 0; padding: 10px 14px; "
    "background: #e8f5e9; border-left: 4px solid #4caf50; "
    "border-radius: 4px;"
)

_HINTS = {
    "loop_matmul": f"""
<details style="{_STYLE}">
  <summary><strong>Hint 1</strong></summary>
  <p>What do the two outer loops iterate over in the result matrix C?</p>
  <details style="{_STYLE}">
    <summary><strong>Hint 2</strong></summary>
    <p>
      The outer loops iterate over row index <code>i</code> (0 to m&minus;1) and
      column index <code>j</code> (0 to p&minus;1).
      The inner loop iterates over the summation index <code>k</code> (0 to n&minus;1).
    </p>
    <details style="{_STYLE}">
      <summary><strong>Show answer</strong></summary>
<pre style="background:#f5f5f5; padding:8px; border-radius:4px;">
for i in range(m):
    for j in range(p):
        for k in range(n):
            C[i, j] += A[i, k] * B[k, j]
</pre>
    </details>
  </details>
</details>
""",
    "vectorised_matmul": f"""
<details style="{_STYLE}">
  <summary><strong>Hint 1</strong></summary>
  <p>Recall Section 3: which NumPy operator performs matrix multiplication?</p>
  <details style="{_STYLE}">
    <summary><strong>Show answer</strong></summary>
<pre style="background:#f5f5f5; padding:8px; border-radius:4px;">
C = A @ B
</pre>
    <p>Equivalently: <code>C = np.matmul(A, B)</code></p>
  </details>
</details>
""",
    "hill_encrypt": f"""
<details style="{_STYLE}">
  <summary><strong>Hint 1</strong></summary>
  <p>Which operator performs matrix multiplication? What does mod 26 do?</p>
  <details style="{_STYLE}">
    <summary><strong>Hint 2</strong></summary>
    <p>Use <code>@</code> for matrix multiplication and <code>% 26</code> to wrap values into 0&ndash;25.</p>
    <details style="{_STYLE}">
      <summary><strong>Show answer</strong></summary>
<pre style="background:#f5f5f5; padding:8px; border-radius:4px;">
cipher_vector = (K @ plain_vector) % 26
</pre>
    </details>
  </details>
</details>
""",
    "valid_key": f"""
<details style="{_STYLE}">
  <summary><strong>Hint 1</strong></summary>
  <p>Two conditions must hold: the determinant must be non-zero, and it must have a modular inverse under 26.</p>
  <details style="{_STYLE}">
    <summary><strong>Hint 2</strong></summary>
    <p>A modular inverse exists when <code>gcd(det, 26) == 1</code>. Use <code>math.gcd()</code>.</p>
    <details style="{_STYLE}">
      <summary><strong>Show answer</strong></summary>
<pre style="background:#f5f5f5; padding:8px; border-radius:4px;">
valid = det != 0 and math.gcd(det, 26) == 1
</pre>
    </details>
  </details>
</details>
""",
    "hill_decrypt": f"""
<details style="{_STYLE}">
  <summary><strong>Hint 1</strong></summary>
  <p>Decryption mirrors encryption &mdash; apply the inverse key matrix the same way.</p>
  <details style="{_STYLE}">
    <summary><strong>Hint 2</strong></summary>
    <p>Use <code>@</code> with the inverse key, then <code>% 26</code>.</p>
    <details style="{_STYLE}">
      <summary><strong>Show answer</strong></summary>
<pre style="background:#f5f5f5; padding:8px; border-radius:4px;">
plain_vector = (K_inv @ cipher_vector) % 26
</pre>
    </details>
  </details>
</details>
""",
    "pagerank_eigen": f"""
<details style="{_STYLE}">
  <summary><strong>Hint 1</strong></summary>
  <p>The PageRank vector is the eigenvector for the largest eigenvalue (&asymp; 1). How do you find the index of the maximum value in an array?</p>
  <details style="{_STYLE}">
    <summary><strong>Hint 2</strong></summary>
    <p>Use <code>np.argmax(np.abs(eigenvalues))</code> to find the index. Extract the column with <code>eigenvectors[:, idx]</code>, then divide by its sum to normalise.</p>
    <details style="{_STYLE}">
      <summary><strong>Show answer</strong></summary>
<pre style="background:#f5f5f5; padding:8px; border-radius:4px;">
idx = np.argmax(np.abs(eigenvalues))
rank_vector = eigenvectors[:, idx]
rank_vector = rank_vector / rank_vector.sum()
</pre>
    </details>
  </details>
</details>
""",
    "pagerank_power": f"""
<details style="{_STYLE}">
  <summary><strong>Hint 1</strong></summary>
  <p>Each iteration simulates one round of link-following. What single operation updates the rank vector?</p>
  <details style="{_STYLE}">
    <summary><strong>Show answer</strong></summary>
<pre style="background:#f5f5f5; padding:8px; border-radius:4px;">
r = G @ r
</pre>
  </details>
</details>
""",
}


def show_hint(exercise_id):
    """Display a collapsible hint box for the given exercise."""
    if exercise_id not in _HINTS:
        print(f"No hints available for '{exercise_id}'.")
        return
    display(HTML(_HINTS[exercise_id]))
