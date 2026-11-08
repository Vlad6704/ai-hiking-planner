import re


class HumanSimulator:
    def __init__(self, rules, threshold=0.60, lead=0.15, clarifications=2):
        self.rules = rules
        self.threshold = threshold
        self.lead = lead
        self.clarifications = clarifications
        self.unmatched = 0
        self.messages = {}

    def answer(self, question):
        matches = {}
        for clause in re.split(r"\band\b|[?;]", question.lower()):
            tokens = set(re.findall(r"[a-z0-9]+", clause))
            scores = []
            for intent, (keywords, _) in self.rules.items():
                groups = [set(group.lower().split()) for group in keywords]
                score = max(
                    (len(group & tokens) / len(group) for group in groups if group),
                    default=0,
                )
                scores.append((score, intent))
            scores.sort(reverse=True)
            if scores and scores[0][0] >= self.threshold:
                if len(scores) == 1 or scores[0][0] - scores[1][0] >= self.lead:
                    matches[scores[0][1]] = scores[0][0]
        if matches:
            self.unmatched = 0
            answer = " ".join(self.rules[key][1] for key in matches)
        else:
            self.unmatched += 1
            if self.unmatched > self.clarifications:
                raise ValueError("human_response_unmatched")
            answer = "Could you clarify what information you need?"
        return dict(
            text=answer,
            matched_intent=list(matches),
            match_score=max(matches.values(), default=0),
        )

    async def deliver(self, agent_id, message_id, text):
        if agent_id != "agent_a":
            raise ValueError("forbidden_delivery")
        self.messages.setdefault(message_id, text)
