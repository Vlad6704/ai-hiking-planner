import asyncio
from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace

from langchain_core.messages import ToolMessage

from app.agents.middleware import PrivateStateMiddleware


def test_parallel_tools_return_independent_checkpoint_updates():
    from contextvars import ContextVar

    class Context:
        def __init__(self):
            self.local = ContextVar('state')

        @contextmanager
        def activate(self, state):
            working = deepcopy(state)
            token = self.local.set(working)
            try:
                yield working
            finally:
                self.local.reset(token)

        def changes(self, before, after):
            return {'observations': {key: value for key, value in after['observations'].items()
                                     if key not in before['observations']}}

    async def run():
        context = Context()
        middleware = PrivateStateMiddleware(context)
        ready = asyncio.Event()
        entered = []
        original = {'observations': {}}

        async def handler(request):
            entered.append(request.tool_call['id'])
            if len(entered) == 2:
                ready.set()
            await ready.wait()
            assert context.local.get()['_tool_call_id'] == request.tool_call['id']
            context.local.get()['observations'][request.tool_call['id']] = {'value': request.tool_call['id']}
            return ToolMessage(content='done', tool_call_id=request.tool_call['id'])

        commands = await asyncio.gather(*(middleware.awrap_tool_call(
            SimpleNamespace(state=original, tool_call={'id': name}), handler)
            for name in ('weather', 'routes')))
        assert original == {'observations': {}}
        assert [set(command.update['observations']) for command in commands] == [{'weather'}, {'routes'}]

    asyncio.run(run())
