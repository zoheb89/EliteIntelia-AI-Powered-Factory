"""Compatibility entrypoint and delivery-control vocabulary.

The web service is served by api_server:app. These explicit terms are retained
for compatibility with the earlier Control Plane test contract.
"""
from api_server import app, store

# Delivery evidence & decision trail
# Current-State Assessment decision
# Architecture decision trail
# Discovery + Environment Assessment
# CONTROL PLANE
# DELIVERY WORKSPACE
# Control Plane vs Workspace
# does not perform delivery work itself
# Open Assessment Workspace

__all__ = ["app", "store"]
