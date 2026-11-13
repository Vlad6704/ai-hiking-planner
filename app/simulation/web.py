"""A local two-chat interface for the existing human-in-the-loop runner."""

import argparse
import asyncio
import logging
import socket
import webbrowser
from contextlib import ExitStack, asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware
import uvicorn

from app.humans.simulator import HumanSimulator
from app.observability.asyncio_logging import capture_asyncio_errors
from app.observability.runtime_logging import configure_logging
from app.observability.trace import redact
from app.simulation.config import Settings
from app.simulation.failures import FAILURE_TOOLS, FailureInjection, apply_failure_override
from app.simulation.manual_services import operator_backend
from app.simulation.outcome import manual_outcome
from app.simulation.runner import SimulationRunner
from app.simulation.scenario import load_scenario, scenarios
from app.simulation.presets import ManualPreset


class BrowserHuman(HumanSimulator):
    def __init__(self, trip):
        super().__init__({})
        self.trip = trip

    async def deliver(self, actor, mid, text):
        self.trip.messages['agent_a'].append(dict(role='agent', text=text))
        await super().deliver(actor, mid, text)


class BrowserRun(SimulationRunner):
    def __init__(self, message, scenario, mode, output, model=None, preset=None, failure_injection=None, seed=42):
        if failure_injection is not None and mode != 'mock':
            raise ValueError('Failure injection is available only in mock mode')
        case = apply_failure_override(load_scenario(scenario, mode), failure_injection)
        case['initial'] = message
        if preset is not None:
            case['manual_preset'] = preset.model_dump(mode='json')
        super().__init__(case, Settings(mode=mode, timeout=3600, peer_timeout=900), seed, model)
        self.failure_injection = failure_injection
        self.preset = preset
        if preset is not None:
            self.trace.metadata['manual_preset'] = preset.model_dump(mode='json')
        self.messages = {'agent_a': [dict(role='human', text=message)], 'agent_b': []}
        self.pending, self.answers = {}, {}
        self.status, self.path, self.report = 'running', None, None
        self.output = output
        self.humans['agent_a'] = BrowserHuman(self)

    async def resolve_interrupt(self, actor, item):
        event = self.present_interrupt(actor, item)
        prompt = dict(item.value, id=str(item.id))
        if prompt['kind'] == 'selection':
            guide_names = {}
            for tool_event in reversed(self.trace.events):
                data = tool_event['data']
                if tool_event['type'] == 'tool.completed' and tool_event['actor'] == actor and data.get('tool') == 'check_guide_availability':
                    output = data.get('output') or {}
                    if output.get('status') in ('success', 'degraded'):
                        guide_names = {guide['guide_id']: guide.get('name') or guide['guide_id']
                                       for guide in output.get('data') or []}
                        break
            prompt['option_labels'] = [guide_names.get(gid, gid) for gid in prompt['options']]
        future = asyncio.get_running_loop().create_future()
        self.pending[actor], self.answers[actor] = prompt, future
        self.messages[actor].append(dict(role='agent', text=prompt['question']))
        try:
            answer = await future
            return self.human_reply(actor, item, answer, interrupt_event=event)
        finally:
            self.pending.pop(actor, None)
            self.answers.pop(actor, None)

    def reply(self, actor, question_id, answer):
        prompt, future = self.pending.get(actor), self.answers.get(actor)
        if not prompt or prompt['id'] != question_id or future is None or future.done():
            raise ValueError('This question is no longer pending')
        answer = answer.strip()
        if not answer:
            raise ValueError('Enter an answer')
        if prompt['kind'] == 'selection' and answer not in {str(n) for n in range(1, len(prompt['options']) + 1)}:
            raise ValueError('Select one of the displayed guides')
        if prompt['kind'] == 'approval':
            if answer.lower() == 'approve':
                answer = 'Approved'
            elif answer.lower().startswith('reject'):
                answer = 'Rejected. ' + answer[6:].strip(' .:')
            else:
                raise ValueError('Approve or reject the displayed proposal')
        self.messages[actor].append(dict(role='human', text=answer))
        future.set_result(answer)

    async def execute(self):
        try:
            await self.run()
            self.status = 'error' if self.error else self.result.status
        except asyncio.CancelledError:
            self.status = 'cancelled'
            self.error = 'Cancelled by the user or server shutdown'
            raise
        except Exception:
            logging.getLogger('app.web').exception('web.session_failed')
            self.status, self.error = 'error', 'Session failed; inspect the runtime log'
        finally:
            self.report = manual_outcome(self, status=self.status)
            self.path = self.trace.write(self.output, self.report, group_by_scenario=False)

    def snapshot(self):
        return dict(id=self.rid, mode=self.settings.mode, status=self.status, messages=self.messages,
                    pending={actor: prompt for actor, prompt in self.pending.items() if not self.answers[actor].done()},
                    error=("We couldn't complete your request. Please try again later." if self.error else None), result=self.result.model_dump(mode='json') if self.result else None,
                    trajectory=bool(self.path), events=redact(self.trace.events),
                    preset=self.preset.model_dump(mode='json') if self.preset else None,
                    failure_injection=self.failure_injection.model_dump(mode='json') if self.failure_injection else None,
                    seed=self.trace.metadata['seed'])


class StartRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    message: str = Field(min_length=1, max_length=8000)
    mode: Literal['mock', 'real'] | None = None
    preset: ManualPreset | None = None
    failure_injection: FailureInjection | None = None
    seed: int = Field(default=42, strict=True)


class ReplyRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    message: str = Field(min_length=1, max_length=8000)
    question_id: str = Field(min_length=1, max_length=100)


def create_app(mode='real', scenario='happy_path', output=Path('trajectories/manual')):
    default_mode = mode
    state = dict(trip=None, task=None, stack=None, real_ready=False, bundled_demo=False)
    backend_lock, session_lock = asyncio.Lock(), asyncio.Lock()

    async def prepare_backend(selected):
        if selected == 'mock' or state['real_ready'] or state['stack'] is None:
            return
        async with backend_lock:
            if not state['real_ready']:
                try:
                    state['bundled_demo'] = await asyncio.to_thread(
                        state['stack'].enter_context, operator_backend('real'))
                except (RuntimeError, OSError) as exc:
                    logging.getLogger('app.web').exception('web.backend_failed')
                    raise HTTPException(503, 'Real data services could not be initialized. Please try again.') from exc
                state['real_ready'] = True

    def presets_available(selected):
        return selected == 'mock' or state['bundled_demo']

    @asynccontextmanager
    async def lifespan(app):
        with ExitStack() as stack, capture_asyncio_errors('web'):
            state['stack'] = stack
            try:
                await prepare_backend(default_mode)
                yield
            finally:
                if state['task'] and not state['task'].done():
                    state['task'].cancel()
                    await asyncio.gather(state['task'], return_exceptions=True)
                await asyncio.to_thread(stack.close)
                state['stack'] = None

    app = FastAPI(lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost'])

    @app.middleware('http')
    async def local_origin(request: Request, call_next):
        from starlette.responses import JSONResponse
        origin = request.headers.get('origin')
        if origin and origin != str(request.base_url).rstrip('/'):
            return JSONResponse({'detail': 'Cross-origin access is not allowed'}, status_code=403)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    def trip_for(identity):
        trip = state['trip']
        if trip is None or trip.rid != identity:
            raise HTTPException(404, 'Session not found')
        return trip

    @app.get('/', response_class=HTMLResponse)
    async def index():
        return Path(__file__).with_name('web.html').read_text(encoding='utf-8')

    @app.get('/api/current')
    async def current():
        return state['trip'].snapshot() if state['trip'] else None

    @app.get('/api/config')
    async def config(mode: Literal['mock', 'real'] | None = None):
        selected = mode or (state['trip'].settings.mode if state['trip'] else default_mode)
        if state['task'] and not state['task'].done() and selected != state['trip'].settings.mode:
            raise HTTPException(409, 'Finish or cancel the active trip before changing data mode')
        await prepare_backend(selected)
        case = load_scenario(scenario, selected)
        default = ManualPreset()
        if case.get('no_guides'):
            default = ManualPreset(name='no_guides_on_date', date=case['no_guides'])
        elif case['stock'].get('rain jacket') == 0 and scenario != 'hitl_rejection':
            default = ManualPreset(name='no_rain_jackets')
        available = presets_available(selected)
        sources = ('Simulation: fixture weather, seeded route catalog and demonstration operator.' if selected == 'mock' else
                   'Real data: live weather and maintained route catalog; guides, inventory and reservations use the demonstration operator.'
                   if state['bundled_demo'] else
                   'Real data: live weather, maintained route catalog and configured external operator.')
        return dict(mode=selected, data_sources=sources, presets_available=available,
                    failure_tools=FAILURE_TOOLS if selected == 'mock' else [],
                    simulation_context=(
                        f"Simulation date: {case['clock'][:10]}. "
                        f"Mock weather dates: {', '.join(day['date'] for day in case['weather']['days'])}. "
                        "Use these dates when planning a hike."
                    ) if selected == 'mock' else None,
                    default_preset=default.model_dump(mode='json'),
                    conditions='Choose session conditions below.' if available else
                    'The external operator controls guide and equipment availability; local presets do not apply.')

    @app.post('/api/session')
    async def start(body: StartRequest):
        async with session_lock:
            return await start_session(body)

    async def start_session(body):
        selected = body.mode or default_mode
        if body.failure_injection is not None and selected != 'mock':
            raise HTTPException(422, 'Failure injection is available only in mock mode')
        if state['task'] and not state['task'].done():
            raise HTTPException(409, 'A trip is already active')
        await prepare_backend(selected)
        if body.preset is not None and not presets_available(selected):
            raise HTTPException(422, 'The external operator controls availability; local presets do not apply')
        trip = BrowserRun(body.message, scenario, selected, output, preset=body.preset,
                          failure_injection=body.failure_injection, seed=body.seed)
        state['trip'] = trip
        state['task'] = asyncio.create_task(trip.execute())
        return trip.snapshot()

    @app.get('/api/session/{identity}')
    async def snapshot(identity: str):
        return trip_for(identity).snapshot()

    @app.post('/api/session/{identity}/{actor}/reply')
    async def reply(identity: str, actor: str, body: ReplyRequest):
        if actor not in ('agent_a', 'agent_b'):
            raise HTTPException(404, 'Unknown participant')
        try:
            trip_for(identity).reply(actor, body.question_id, body.message)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {'accepted': True}

    @app.post('/api/session/{identity}/cancel')
    async def cancel(identity: str):
        trip_for(identity)
        if state['task'] and not state['task'].done():
            state['task'].cancel()
            await asyncio.gather(state['task'], return_exceptions=True)
        return state['trip'].snapshot()

    @app.get('/api/session/{identity}/trajectory')
    async def trajectory(identity: str):
        trip = trip_for(identity)
        if not trip.path:
            raise HTTPException(409, 'The trip has not finished')
        return FileResponse(trip.path, media_type='application/json', filename=trip.path.name)

    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=['mock', 'real'], default='real')
    parser.add_argument('--scenario', choices=scenarios(), default='happy_path')
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    configure_logging('web')
    with socket.create_server(('127.0.0.1', args.port)) as listener:
        url = f'http://127.0.0.1:{listener.getsockname()[1]}'
        app = create_app(args.mode, args.scenario)
        async def serve():
            server = uvicorn.Server(uvicorn.Config(app, log_config=None, access_log=False))
            task = asyncio.create_task(server.serve(sockets=[listener]))
            while not server.started and not task.done():
                await asyncio.sleep(0.05)
            if server.started:
                print(f'Hiking planner: {url}', flush=True)
                if not args.no_browser:
                    await asyncio.to_thread(webbrowser.open, url)
            await task
        asyncio.run(serve())


if __name__ == '__main__':
    main()
