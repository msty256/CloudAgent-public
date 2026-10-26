"""REPL module for CloudAgent."""

from .background_escape import BackgroundEscape

__all__ = ['CloudagentREPL', 'BackgroundEscape']


def __getattr__(name: str):
    if name == 'CloudagentREPL':
        from .core import CloudagentREPL

        globals()[name] = CloudagentREPL
        return CloudagentREPL
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
