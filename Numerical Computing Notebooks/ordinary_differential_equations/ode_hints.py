"""Collapsible hint boxes for notebook exercises."""

from IPython.display import display, HTML

_STYLE = (
    "margin: 8px 0; padding: 10px 14px; "
    "background: #e8f5e9; border-left: 4px solid #4caf50; "
    "border-radius: 4px;"
)

_HINTS = {
    "forward_euler": f"""
<details style="{_STYLE}">
  <summary><strong>Hint 1</strong></summary>
  <p>The update rule is: next value = current value + step size &times; slope at current point.</p>
  <details style="{_STYLE}">
    <summary><strong>Hint 2</strong></summary>
    <p>In code: <code>y[i+1] = y[i] + h * f(t[i], y[i])</code>.</p>
    <details style="{_STYLE}">
      <summary><strong>Show answer</strong></summary>
<pre style="background:#f5f5f5; padding:8px; border-radius:4px;">
for i in range(len(t) - 1):
    y[i+1] = y[i] + h * f(t[i], y[i])
</pre>
    </details>
  </details>
</details>
""",
    "rk2_heun": f"""
<details style="{_STYLE}">
  <summary><strong>Hint 1</strong></summary>
  <p>First compute the slope at the start (<code>k1</code>). Then use Forward Euler to predict the endpoint and compute a second slope (<code>k2</code>). Average both slopes.</p>
  <details style="{_STYLE}">
    <summary><strong>Hint 2</strong></summary>
    <p><code>k1 = f(t[i], y[i])</code>, <code>k2 = f(t[i+1], y[i] + h * k1)</code>, then <code>y[i+1] = y[i] + (h/2) * (k1 + k2)</code>.</p>
    <details style="{_STYLE}">
      <summary><strong>Show answer</strong></summary>
<pre style="background:#f5f5f5; padding:8px; border-radius:4px;">
for i in range(len(t) - 1):
    k1 = f(t[i], y[i])
    k2 = f(t[i+1], y[i] + h * k1)
    y[i+1] = y[i] + (h / 2) * (k1 + k2)
</pre>
    </details>
  </details>
</details>
""",
    "rk2_midpoint": f"""
<details style="{_STYLE}">
  <summary><strong>Hint 1</strong></summary>
  <p>Compute the slope at the start (<code>k1</code>), step halfway using that slope, then compute the slope at the midpoint (<code>k2</code>). Use only <code>k2</code> for the full step.</p>
  <details style="{_STYLE}">
    <summary><strong>Hint 2</strong></summary>
    <p><code>k1 = f(t[i], y[i])</code>, <code>k2 = f(t[i] + h/2, y[i] + (h/2) * k1)</code>, then <code>y[i+1] = y[i] + h * k2</code>.</p>
    <details style="{_STYLE}">
      <summary><strong>Show answer</strong></summary>
<pre style="background:#f5f5f5; padding:8px; border-radius:4px;">
for i in range(len(t) - 1):
    k1 = f(t[i], y[i])
    k2 = f(t[i] + h / 2, y[i] + (h / 2) * k1)
    y[i+1] = y[i] + h * k2
</pre>
    </details>
  </details>
</details>
""",
    "rk4": f"""
<details style="{_STYLE}">
  <summary><strong>Hint 1</strong></summary>
  <p>Compute four slopes: <code>k1</code> at the start, <code>k2</code> and <code>k3</code> at the midpoint, and <code>k4</code> at the end. Combine them with weights 1, 2, 2, 1.</p>
  <details style="{_STYLE}">
    <summary><strong>Hint 2</strong></summary>
    <p><code>k2</code> uses <code>k1</code> to step to t + h/2. <code>k3</code> uses <code>k2</code> to step to t + h/2 again. <code>k4</code> uses <code>k3</code> to step to t + h.</p>
    <details style="{_STYLE}">
      <summary><strong>Show answer</strong></summary>
<pre style="background:#f5f5f5; padding:8px; border-radius:4px;">
for i in range(len(t) - 1):
    k1 = f(t[i], y[i])
    k2 = f(t[i] + h/2, y[i] + h/2 * k1)
    k3 = f(t[i] + h/2, y[i] + h/2 * k2)
    k4 = f(t[i] + h, y[i] + h * k3)
    y[i+1] = y[i] + (h / 6) * (k1 + 2*k2 + 2*k3 + k4)
</pre>
    </details>
  </details>
</details>
""",
    "rk4_system": f"""
<details style="{_STYLE}">
  <summary><strong>Hint 1</strong></summary>
  <p>The formula is identical to the scalar RK4, but <code>y</code> and each <code>k</code> are now NumPy arrays. Use <code>np.array(y0, dtype=float)</code> to initialise.</p>
  <details style="{_STYLE}">
    <summary><strong>Hint 2</strong></summary>
    <p>Store results in a 2-D array: <code>Y = np.zeros((len(t), len(y0)))</code>. Each row <code>Y[i]</code> is the state vector at time <code>t[i]</code>.</p>
    <details style="{_STYLE}">
      <summary><strong>Show answer</strong></summary>
<pre style="background:#f5f5f5; padding:8px; border-radius:4px;">
for i in range(len(t) - 1):
    k1 = f(t[i], Y[i])
    k2 = f(t[i] + h/2, Y[i] + h/2 * k1)
    k3 = f(t[i] + h/2, Y[i] + h/2 * k2)
    k4 = f(t[i] + h, Y[i] + h * k3)
    Y[i+1] = Y[i] + (h / 6) * (k1 + 2*k2 + 2*k3 + k4)
</pre>
    </details>
  </details>
</details>
""",
    "van_der_pol": f"""
<details style="{_STYLE}">
  <summary><strong>Hint 1</strong></summary>
  <p>Let <code>x = state[0]</code> and <code>v = state[1]</code>. The first equation is: dx/dt = v. The second equation comes from the original ODE.</p>
  <details style="{_STYLE}">
    <summary><strong>Hint 2</strong></summary>
    <p><code>dxdt = v</code> and <code>dvdt = mu * (1 - x**2) * v - x</code>. Return them as a NumPy array.</p>
    <details style="{_STYLE}">
      <summary><strong>Show answer</strong></summary>
<pre style="background:#f5f5f5; padding:8px; border-radius:4px;">
x, v = state[0], state[1]
dxdt = v
dvdt = mu * (1 - x**2) * v - x
return np.array([dxdt, dvdt])
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
