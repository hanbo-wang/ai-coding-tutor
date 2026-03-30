"""Collapsible hint boxes for notebook exercises."""

from IPython.display import display, HTML

_STYLE = (
    "margin: 8px 0; padding: 10px 14px; "
    "background: #e8f5e9; border-left: 4px solid #4caf50; "
    "border-radius: 4px;"
)

_HINTS = {
    "naive_dft": f"""
<details style="{_STYLE}">
  <summary><strong>Hint 1</strong></summary>
  <p>For each output bin <code>k</code>, multiply the input signal point-by-point with a complex exponential at frequency <code>k</code>, then sum the products.</p>
  <details style="{_STYLE}">
    <summary><strong>Hint 2</strong></summary>
    <p>The complex exponential for bin <code>k</code> and sample <code>n</code> is <code>np.exp(-2j * np.pi * k * n / N)</code>. Use a loop over <code>k</code> (outer) and <code>n</code> (inner).</p>
    <details style="{_STYLE}">
      <summary><strong>Show answer</strong></summary>
<pre style="background:#f5f5f5; padding:8px; border-radius:4px;">
for k in range(N):
    for n in range(N):
        X[k] += x[n] * np.exp(-2j * np.pi * k * n / N)
</pre>
    </details>
  </details>
</details>
""",
    "noisy_spectrum": f"""
<details style="{_STYLE}">
  <summary><strong>Hint 1</strong></summary>
  <p>Use <code>np.fft.rfftfreq</code> to build the frequency axis (the sample spacing is <code>d = 1 / fs_noisy</code>). Use <code>np.fft.rfft</code> to compute the FFT, then <code>np.abs</code> to get the magnitudes.</p>
  <details style="{_STYLE}">
    <summary><strong>Show answer</strong></summary>
<pre style="background:#f5f5f5; padding:8px; border-radius:4px;">
freqs_n = np.fft.rfftfreq(N_noisy, d=1/fs_noisy)
X_clean = np.abs(np.fft.rfft(clean))
X_noisy = np.abs(np.fft.rfft(noisy))
</pre>
  </details>
</details>
""",
    "twiddle_factors": f"""
<details style="{_STYLE}">
  <summary><strong>Hint 1</strong></summary>
  <p>Each twiddle factor is <code>W_N^k = exp(-j 2&pi; k / N)</code>. Build an array of these for <code>k = 0, 1, &hellip;, N/2 &minus; 1</code>.</p>
  <details style="{_STYLE}">
    <summary><strong>Hint 2</strong></summary>
    <p>Use <code>np.exp(-2j * np.pi * np.arange(N // 2) / N)</code>.</p>
    <details style="{_STYLE}">
      <summary><strong>Show answer</strong></summary>
<pre style="background:#f5f5f5; padding:8px; border-radius:4px;">
return np.exp(-2j * np.pi * np.arange(N // 2) / N)
</pre>
    </details>
  </details>
</details>
""",
    "cooley_tukey_fft": f"""
<details style="{_STYLE}">
  <summary><strong>Hint 1</strong></summary>
  <p>Split <code>x</code> into even-indexed and odd-indexed elements. Recursively compute the FFT of each half. Then combine using the butterfly: <code>X[k] = E[k] + W * O[k]</code> and <code>X[k+N/2] = E[k] &minus; W * O[k]</code>.</p>
  <details style="{_STYLE}">
    <summary><strong>Hint 2</strong></summary>
    <p>Even elements: <code>x[0::2]</code>. Odd elements: <code>x[1::2]</code>. Twiddle factors: <code>np.exp(-2j * np.pi * np.arange(N//2) / N)</code>. Precompute <code>T = twiddle * O</code>, then <code>X[:N//2] = E + T</code> and <code>X[N//2:] = E &minus; T</code>.</p>
    <details style="{_STYLE}">
      <summary><strong>Show answer</strong></summary>
<pre style="background:#f5f5f5; padding:8px; border-radius:4px;">
E = cooley_tukey_fft(x[0::2])
O = cooley_tukey_fft(x[1::2])
T = np.exp(-2j * np.pi * np.arange(N // 2) / N) * O
X = np.zeros(N, dtype=complex)
X[:N // 2] = E + T
X[N // 2:] = E - T
return X
</pre>
    </details>
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
