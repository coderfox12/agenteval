"""
Session-Hooks für die Funktionalitäts-Evaluation (D1).

pytest erkennt pytest_sessionstart/pytest_sessionfinish NUR, wenn sie in
conftest.py stehen – Funktionen mit demselben Namen in einer regulären
test_*.py-Datei werden von pytest NIE aufgerufen (mit einem minimalen
Wegwerf-Testfall verifiziert). Die eigentliche Logik bleibt in
test_functionality.py (warm_caches/finalize_and_report), hier werden die
beiden Funktionen nur an die pytest-Hooks angeschlossen.
"""

import test_functionality as tf


def pytest_sessionstart(session):
    tf.warm_caches()


def pytest_sessionfinish(session, exitstatus):
    tf.finalize_and_report()
