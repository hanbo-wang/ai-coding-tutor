Numerical Computing Notebooks
==============================

A collection of interactive Jupyter notebooks for learning numerical
methods. Each topic folder contains student notebooks (with fill-in
exercises), answer keys, and support modules for hints and automated
checking.


1. Linear Algebra (linear_algebra/)
------------------------------------
Core linear algebra topics, from basic vector and matrix arithmetic
through to eigenvalue applications such as the Hill cipher and PageRank.

Notebooks:
  vectors_and_matrices.ipynb
    Vectors, matrices, dot products, norms, transpose, and matrix
    multiplication.

  core_concepts_and_applications.ipynb
    Determinants, inverses, rank, linear systems, eigenvalues, Hill
    cipher, and PageRank.

Support modules:
  linalg_hints.py    Progressive hint boxes for each exercise.
  linalg_verify.py   Automated test functions that check student answers.

Answer keys:
  vectors_and_matrices_test.ipynb
  core_concepts_and_applications_test.ipynb


2. Ordinary Differential Equations (ordinary_differential_equations/)
----------------------------------------------------------------------
Numerical methods for solving ODEs, from Forward Euler through to
the classical RK4 method, with applications to coupled systems such
as predator-prey dynamics and nonlinear oscillators.

Notebooks:
  euler_and_rk2.ipynb
    Forward Euler, Backward Euler, Trapezoidal, RK2 (Heun), and
    RK2 (Midpoint) methods, with accuracy and stability analysis.

  rk4_and_ode_systems.ipynb
    Classical RK4 method with fourth-order convergence verification,
    extension to ODE systems, Lotka-Volterra predator-prey model,
    order reduction for second-order ODEs, and the Van der Pol
    oscillator with limit cycle visualisation.

Support modules:
  ode_hints.py    Progressive hint boxes for each exercise.
  ode_verify.py   Automated test functions that check student answers.

Answer keys:
  euler_and_rk2_test.ipynb
  rk4_and_ode_systems_test.ipynb


3. Root-Finding Methods (root_finding/)
----------------------------------------
Root-finding algorithms for solving nonlinear equations, covering
fixed-point iteration, Newton's method, and the Secant method.

Notebooks:
  newton_and_secant.ipynb
    Classification of root-finding methods, fixed-point iteration and
    cobweb diagrams, Newton's method with quadratic convergence,
    Secant method with golden-ratio convergence order, convergence
    comparison, and Newton's fractal visualisation.

Support modules:
  rootfinding_hints.py    Progressive hint boxes for each exercise.
  rootfinding_verify.py   Automated test functions that check student answers.

Answer keys:
  newton_and_secant_test.ipynb


4. Fourier Transform (fourier_transform/)
------------------------------------------
The Discrete Fourier Transform and Fast Fourier Transform, from
the core intuition of frequency-domain correlation through to
practical usage with NumPy's FFT.

Notebooks:
  dft_and_fft.ipynb
    Sine wave fundamentals, correlation with sinusoids, DFT
    derivation and naive implementation, computational cost
    analysis, and practical FFT usage with NumPy (including
    frequency extraction from noisy signals).

  supplementary_cooley_tukey_fft.ipynb
    Full derivation of the Cooley-Tukey radix-2 FFT algorithm:
    even/odd decomposition, twiddle factors, butterfly symmetry,
    recursive implementation, and timing comparison.

Support modules:
  fourier_hints.py    Progressive hint boxes for each exercise.
  fourier_verify.py   Automated test functions that check student answers.

Answer keys:
  dft_and_fft_test.ipynb
  supplementary_cooley_tukey_fft_test.ipynb
