"""Pydantic request/response models — the API contract.

Kept separate from the ORM models on purpose: the wire format should be able to
stay still while the domain model changes underneath it. No endpoint returns an
ORM instance.
"""
