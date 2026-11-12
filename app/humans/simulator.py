import re


class HumanSimulator:
    def __init__(self, rules, threshold=0.60, lead=0.15, clarifications=2, *, consent_terms=None):
        self.rules = rules
        self.threshold = threshold
        self.lead = lead
        self.clarifications = clarifications
        self.unmatched = 0
        self.messages = {}
        self.consent_terms = consent_terms
        self.route_preference_disclosed = False

    def answer(self, question, *, intent=None, proposal=None, original_proposal=None):
        if intent == "substitution" and self.consent_terms is not None:
            expected = self.consent_terms
            route_id = expected["route_id"]
            if original_proposal is not None and not self.route_preference_disclosed:
                route_id = original_proposal["route_id"]
            if (not proposal or proposal.get("route_id") != route_id
                    or proposal.get("date") not in expected["dates"]
                    or proposal.get("equipment") != expected["equipment"]):
                self.unmatched = 0
                return dict(text="No, I decline these terms; they do not match my scenario preferences.",
                            matched_intent=["substitution"], match_score=1.0)
        matches = {}
        for clause in re.split(r"\band\b|[?;]", question.lower()):
            tokens = set(re.findall(r"[a-z0-9]+", clause))
            scores = []
            for rule_intent, (keywords, _) in self.rules.items():
                if (intent is not None and rule_intent != intent) or (
                    intent is None and rule_intent == "substitution"
                ):
                    continue
                groups = [set(re.findall(r"[a-z0-9]+", group.lower())) for group in keywords]
                scored = [(len(group & tokens) / len(group), group & tokens)
                          for group in groups if group]
                score = max((value for value, _ in scored), default=0)
                evidence = set().union(*(words for value, words in scored if value == score))
                scores.append((score, rule_intent, evidence))
            best = max((score for score, _, _ in scores), default=0)
            candidates = [(score, name, evidence) for score, name, evidence in scores
                          if score >= self.threshold and (score == best or best - score < self.lead)]
            for score, name, evidence in candidates:
                competing = set().union(*(words for _, other, words in candidates if other != name))
                if len(candidates) == 1 or evidence - competing:
                    matches[name] = max(score, matches.get(name, 0))
        if matches:
            matches = {name: matches[name] for name in self.rules if name in matches}
            if "route" in matches:
                self.route_preference_disclosed = True
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
