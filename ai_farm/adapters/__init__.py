"""Adapters: one interface, any vendor."""
from .base import AgentAdapter, AgentReply
from .registry import register, get_adapter

__all__ = ["AgentAdapter", "AgentReply", "register", "get_adapter"]
