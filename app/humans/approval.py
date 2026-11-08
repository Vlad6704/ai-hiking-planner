import json
from uuid import uuid4


class ApprovalRegistry:
    def __init__(self):
        self.records = {}

    def select(self, response, options):
        if not response.isdigit() or not 1 <= int(response) <= len(options):
            raise ValueError("invalid_guide_choice")
        return options[int(response) - 1]

    def record(self, request_id, proposal, decision):
        self.records.pop(request_id, None)
        if decision.strip().lower().rstrip(".") == "approved":
            ref = str(uuid4())
            self.records[request_id] = (ref, json.dumps(proposal, sort_keys=True))
            return ref
        return None

    def require(self, request_id, ref, proposal):
        if self.records.get(request_id) != (ref, json.dumps(proposal, sort_keys=True)):
            raise ValueError("missing_approval")
