import showreel  # noqa: F401


def test_package_imports():
    assert showreel is not None


def test_main_compiles():
    import os
    import py_compile
    py_compile.compile(os.path.join(os.path.dirname(__file__), "..", "..", "main.py"), doraise=True)
