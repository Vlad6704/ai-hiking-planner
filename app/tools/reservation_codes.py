"""Process-local short reservation identities for mock and demo providers."""

import secrets
import threading


class ReservationCodes:
    def __init__(self):
        self.by_request = {}
        self.owners = {}
        self.lock = threading.Lock()

    def issue(self, request_id):
        key = str(request_id)
        with self.lock:
            if key in self.by_request:
                return self.by_request[key]
            for _ in range(32):
                code = "TR-" + "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(8))
                if code not in self.owners:
                    self.by_request[key] = code
                    self.owners[code] = key
                    return code
        raise ValueError("reservation_code_unavailable")


reservation_codes = ReservationCodes()
