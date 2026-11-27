class DrillError(Exception):
    """A refused request. Always carries a machine-readable code."""

    def __init__(self, code, message, details=None):
        super().__init__(message)
        self.code, self.message, self.details = code, message, details

    def to_dict(self):
        return {"error": {"code": self.code, "message": self.message, "details": self.details}}
