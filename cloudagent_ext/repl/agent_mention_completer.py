"""Facade — repl/agent_mention_completer.py has been moved to cloudagent_ext.

The full implementation now lives in
:mod:`cloudagent_ext.utils.agent_mention_completer`. This module re-exports
the public surface so legacy callers using
``from src.repl.agent_mention_completer import AgentMentionCompleter``
keep working without modification.
"""

from cloudagent_ext.utils.agent_mention_completer import (  # noqa: F401
    AgentMentionCompleter,
)

__all__ = ['AgentMentionCompleter']
