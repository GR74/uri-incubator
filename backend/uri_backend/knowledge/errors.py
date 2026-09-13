from uri_backend.errors import URIBackendError


class ImmutableRecordError(URIBackendError):
    """Raised when code attempts to rewrite published knowledge."""
