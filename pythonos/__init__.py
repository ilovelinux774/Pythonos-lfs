"""The portable PythonOS framework.

The hosted desktop imports this package directly from a normal Python
installation. The native Alpine image keeps its low-level boot package under
``system/usr/lib/pythonos`` and shares the same application contracts.
"""

__version__ = "0.2.0"
__codename__ = "Constrictor"
__pretty_name__ = f"PythonOS {__version__} \"{__codename__}\""
