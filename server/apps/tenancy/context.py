"""Request/task-local tenant scope. Never infer tenancy from submitted object IDs."""
from contextlib import contextmanager
from contextvars import ContextVar

_active = ContextVar("active_organization", default=None)

def organization_id():
    return _active.get()

@contextmanager
def organization_context(organization):
    token = _active.set(getattr(organization, "pk", organization))
    try:
        yield
    finally:
        _active.reset(token)

_branch = ContextVar("active_branch", default=None)


def branch_id():
    return _branch.get()


@contextmanager
def branch_context(branch):
    token = _branch.set(getattr(branch, "pk", branch))
    try:
        yield
    finally:
        _branch.reset(token)
