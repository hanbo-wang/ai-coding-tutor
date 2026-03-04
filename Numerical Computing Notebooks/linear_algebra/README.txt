Linear Algebra — File Overview
===============================

This folder covers core linear algebra topics, from basic vector and
matrix arithmetic through to eigenvalue applications.

Notebooks
---------
vectors_and_matrices.ipynb
  Vectors, matrices, dot products, norms, transpose, and matrix multiplication.

vectors_and_matrices_test.ipynb
  Answer key for vectors_and_matrices.

core_concepts_and_applications.ipynb
  Determinants, inverses, rank, linear systems, eigenvalues, Hill cipher, and PageRank.

core_concepts_and_applications_test.ipynb
  Answer key for core_concepts_and_applications.

Support Modules
---------------
linalg_hints.py
  Progressive hint boxes for each exercise.

linalg_verify.py
  Automated test functions that check student answers.

Library Requirements
--------------------
Third-party packages (install with pip):
- numpy
  Used in all notebooks and `linalg_verify.py` for matrix operations and linear algebra.
- matplotlib
  Used in all notebooks for plotting and visualisation.
- networkx
  Used in `core_concepts_and_applications.ipynb` for the PageRank directed graph.

Standard library modules (built in, no installation needed):
- math
  Used in `core_concepts_and_applications.ipynb` and `linalg_verify.py` for `math.gcd()` in the Hill cipher section.
- time
  Used in `vectors_and_matrices.ipynb` for timing loop-based vs vectorised matrix multiplication.

Jupyter built-in:
- IPython.display
  Used in `linalg_hints.py` to render HTML hint boxes.
