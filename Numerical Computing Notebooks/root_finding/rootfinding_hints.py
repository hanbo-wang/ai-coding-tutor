"""Collapsible hint boxes for notebook exercises."""

from IPython.display import display, HTML

_STYLE = (
    "margin: 8px 0; padding: 10px 14px; "
    "background: #e8f5e9; border-left: 4px solid #4caf50; "
    "border-radius: 4px;"
)

_HINTS = {
    "newton_method": f"""
<details style="{_STYLE}">
  <summary><strong>Hint 1</strong></summary>
  <p>Starting from <code>x0</code>, each step uses the tangent-line formula to compute the next approximation and appends it to <code>history</code>.</p>
  <details style="{_STYLE}">
    <summary><strong>Hint 2</strong></summary>
    <p>The update is <code>x = x - g(x) / dg(x)</code>. Stop when <code>abs(g(x)) &lt; tol</code> or after <code>max_iter</code> iterations.</p>
    <details style="{_STYLE}">
      <summary><strong>Show answer</strong></summary>
<pre style="background:#f5f5f5; padding:8px; border-radius:4px;">
for _ in range(max_iter):
    x = x - g(x) / dg(x)
    history.append(x)
    if abs(g(x)) < tol:
        break
</pre>
    </details>
  </details>
</details>
""",
    "secant_method": f"""
<details style="{_STYLE}">
  <summary><strong>Hint 1</strong></summary>
  <p>Use the slope through the two most recent points instead of the derivative. After computing the new value, shift: <code>x0, x1 = x1, x_new</code>.</p>
  <details style="{_STYLE}">
    <summary><strong>Hint 2</strong></summary>
    <p>The update is <code>x_new = x1 - g(x1) * (x1 - x0) / (g(x1) - g(x0))</code>.</p>
    <details style="{_STYLE}">
      <summary><strong>Show answer</strong></summary>
<pre style="background:#f5f5f5; padding:8px; border-radius:4px;">
for _ in range(max_iter):
    g_x0, g_x1 = g(x0), g(x1)
    x_new = x1 - g_x1 * (x1 - x0) / (g_x1 - g_x0)
    history.append(x_new)
    x0, x1 = x1, x_new
    if abs(g(x1)) < tol:
        break
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
