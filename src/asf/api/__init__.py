"""API endpoints and presentation interfaces.

Only the framework-free :class:`FactoryService` is re-exported here; the
FastAPI application lives in :mod:`asf.api.app` and is imported explicitly
by assemblies, so importing this package never requires FastAPI.
"""

from asf.api.service import FactoryService

__all__ = ["FactoryService"]
