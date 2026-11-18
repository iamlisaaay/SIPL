"""SIPL Language Toolkit.

Public API (stable within 1.x):

* :func:`sipl.parser.parse` – text -> typed AST with source spans
* :func:`sipl.visualization.derivation.derivation_tree` – derivation tree by the course BNF
* :func:`sipl.semantics.build.sem_P` – semantic term of a program
* :func:`sipl.semantics.evaluate.apply_term` – apply a term to a state with a rule trace
* :func:`sipl.prover.assistant.prove` – correctness-proof assistant for loop programs
"""

__version__ = "1.0.0"

from sipl.diagnostics import Diagnostic, SiplError, SiplSyntaxError
from sipl.parser import parse, parse_formula

__all__ = ["Diagnostic", "SiplError", "SiplSyntaxError", "__version__", "parse", "parse_formula"]
