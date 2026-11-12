"""Checkpoint updates for one agent's isolated tool execution."""

from langchain.agents.middleware import AgentMiddleware
from langgraph.types import Command


class PrivateStateMiddleware(AgentMiddleware):
    def __init__(self, context):
        self.context = context

    async def awrap_tool_call(self, request, handler):
        with self.context.activate(request.state) as working:
            working['_tool_call_id'] = request.tool_call['id']
            response = await handler(request)
            if working.get('result'):
                working['trip_status'] = 'completed'
            elif working.get('outbox') != request.state.get('outbox'):
                working['trip_status'] = 'waiting_for_peer'
            updates = self.context.changes(request.state, working)
        if isinstance(response, Command):
            updates.update(response.update or {})
        else:
            updates['messages'] = [response]
        return Command(update=updates)

    async def aafter_model(self, state, runtime):
        calls = state['messages'][-1].tool_calls
        human = next((call for call in calls if call['name'] in ('ask_human', 'send_to_customer')), None)
        if human is not None:
            return {'trip_status': 'waiting_for_human',
                    'pending_interaction': {'tool_call_id': human['id'], 'tool': human['name'],
                                            'arguments': human['args']}}
        if self.context.actor != 'agent_b':
            return None
        booking = next((call for call in calls if call['name'] == 'create_tour_reservation'), None)
        if booking is None:
            return None
        with self.context.activate(state) as working:
            try:
                self.context.prepare_booking(booking['args'], booking['id'])
            except ValueError:
                # The tool returns its normal typed validation failure.
                return None
            return self.context.changes(state, working)
