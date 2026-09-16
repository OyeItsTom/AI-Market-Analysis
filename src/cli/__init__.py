"""Command-line callers of the application layer.

A second caller beside :mod:`src.dashboard`: each module here parses
arguments, calls the same :mod:`src.application` functions the dashboard
calls, prints what happened and exits. Nothing here fetches, measures,
decides or stores; the boundary suite pins that this package imports only
the standard library and :mod:`src.application`.
"""
