"""Strategic (four-step) transport model for Singapore: a personal desk study."""
import os

# The matrices here are small (332 x 332): OpenBLAS worker threads cost more than they save, several times over
# on a busy machine, and a threaded dot product sums in an order that depends on the number of cores. One BLAS
# thread keeps the run fast and its floating-point results independent of the core count. This only takes effect
# if it is set before NumPy is first imported, which is why tests/conftest.py sets it too.
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
