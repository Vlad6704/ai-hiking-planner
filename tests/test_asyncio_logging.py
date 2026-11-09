import asyncio
import importlib
import logging
import threading

import pytest

from test_runtime_logging import records, runtime


def test_callback_failure_records_real_socket_addresses_and_chains(runtime, tmp_path):
    diagnostics = importlib.import_module('app.observability.asyncio_logging')
    path = runtime.configure_logging('customer', tmp_path)
    chained = []

    async def run():
        peers = []
        async def accept(reader, writer):
            peers.append(writer)
        server = await asyncio.start_server(accept, '127.0.0.1', 0)
        _, writer = await asyncio.open_connection('127.0.0.1', server.sockets[0].getsockname()[1])
        local, peer = writer.get_extra_info('sockname'), writer.get_extra_info('peername')

        class ClosingCallback:
            def get_extra_info(self, name):
                return writer.get_extra_info(name)
            def fail(self):
                error = ConnectionResetError(10054, 'Remote reset')
                error.winerror = 10054
                raise error

        loop = asyncio.get_running_loop()
        previous = lambda loop, context: chained.append(context)
        loop.set_exception_handler(previous)
        with diagnostics.capture_asyncio_errors('customer', loop):
            loop.call_soon(ClosingCallback().fail)
            await asyncio.sleep(0.02)
        assert loop.get_exception_handler() is previous
        writer.close()
        await writer.wait_closed()
        for connection in peers:
            connection.close()
            await connection.wait_closed()
        server.close()
        await server.wait_closed()
        return local, peer

    local, peer = asyncio.run(run())
    row = next(row for row in records(path) if row['event'] == 'asyncio.exception')
    assert row['exception']['winerror'] == 10054
    assert 'ClosingCallback.fail' in row['fields']['callback']
    assert 'in fail' in row['exception']['traceback']
    assert row['fields']['local_address'] == list(local)
    assert row['fields']['peer_address'] == list(peer)
    assert row['component'] == 'customer'
    assert len(chained) == 1


@pytest.mark.parametrize('error_type', [OSError, ValueError])
def test_absent_or_closed_transport_cannot_break_logging(runtime, tmp_path, error_type):
    diagnostics = importlib.import_module('app.observability.asyncio_logging')
    path = runtime.configure_logging('test', tmp_path)
    class Closed:
        def get_extra_info(self, name):
            raise error_type('Socket closed')
    async def run():
        loop = asyncio.get_running_loop()
        with diagnostics.capture_asyncio_errors('test'):
            loop.call_exception_handler({'message': 'Closed transport', 'transport': Closed()})
            loop.call_exception_handler({'message': 'No transport'})
            with pytest.raises(ConnectionResetError):
                raise ConnectionResetError('Awaited errors still propagate')
    asyncio.run(run())
    rows = [row for row in records(path) if row['event'] == 'asyncio.exception']
    assert len(rows) == 2
    assert all(row['fields']['peer_address'] is None for row in rows)


def test_background_loop_has_its_own_component(runtime, tmp_path):
    diagnostics = importlib.import_module('app.observability.asyncio_logging')
    path = runtime.configure_logging('customer', tmp_path)
    def worker():
        async def run():
            with diagnostics.capture_asyncio_errors('operator_demo'):
                asyncio.get_running_loop().call_exception_handler({'exception': ValueError('background failure')})
        asyncio.run(run())
    thread = threading.Thread(target=worker, name='demo-test')
    thread.start()
    thread.join(timeout=5)
    assert not thread.is_alive()
    logging.getLogger('app.test').info('main')
    rows = records(path)
    assert rows[0]['component'] == 'operator_demo' and rows[0]['thread_name'] == 'demo-test'
    assert rows[1]['component'] == 'customer'


def test_nested_application_scopes_do_not_duplicate_callback_records(runtime, tmp_path):
    diagnostics = importlib.import_module('app.observability.asyncio_logging')
    path = runtime.configure_logging('customer', tmp_path)
    async def run():
        with diagnostics.capture_asyncio_errors('manual_customer'):
            with diagnostics.capture_asyncio_errors('simulation'):
                asyncio.get_running_loop().call_exception_handler({'exception': RuntimeError('nested callback')})
    asyncio.run(run())
    assert len([row for row in records(path) if row['event'] == 'asyncio.exception']) == 1
