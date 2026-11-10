"""Explicit operator setup; no provisioning, inference or secret arguments."""
import argparse
import json
import sys
import uuid

from prosaic_harness import StoreError, StoreIncompatible, StoreBusy
from prosaic_harness.contracts import seal
from .store import PostgresRunStore


def check_write(store):
    async def permissions(conn):
        for table in ('receipts', 'runs', 'leases'):
            allowed = await (await conn.execute('SELECT pg_catalog.has_table_privilege(%s,%s)',
                ('prosaic_harness.' + table, 'DELETE'))).fetchone()
            if not allowed[0]:
                raise StoreIncompatible('write diagnostic requires separate DELETE-capable credentials')
    store._transport.call(permissions)
    run_id, invocation_id = uuid.uuid4().hex, uuid.uuid4().hex
    state = seal({'run_id': run_id, 'inputs': {'diagnostic': True}})
    receipt = seal({'run_id': run_id, 'id': invocation_id, 'events': []})
    async def cleanup(conn):
        row = await (await conn.execute('SELECT owner FROM prosaic_harness.leases '
            'WHERE namespace=%s AND run_id=%s FOR UPDATE', (store.namespace, run_id))).fetchone()
        if row and row[0] is not None:
            raise StoreBusy('diagnostic cleanup incomplete; reconcile the reserved diagnostic namespace')
        await conn.execute('DELETE FROM prosaic_harness.receipts WHERE namespace=%s AND run_id=%s AND invocation_id=%s',
                           (store.namespace, run_id, invocation_id))
        await conn.execute('DELETE FROM prosaic_harness.runs WHERE namespace=%s AND run_id=%s', (store.namespace, run_id))
        await conn.execute('DELETE FROM prosaic_harness.leases WHERE namespace=%s AND run_id=%s', (store.namespace, run_id))
    try:
        with store.lease(run_id) as lease:
            first = store.create_run(run_id, state, lease)
            second = store.save_run(run_id, state, first, lease)
            store.save_receipt(run_id, invocation_id, receipt, lease)
            if store.load_run(run_id).revision != second or store.load_receipt(run_id, invocation_id) != receipt:
                raise StoreIncompatible('diagnostic persistence verification failed')
    finally:
        # Cleanup must acknowledge success before the command can pass.
        store._transport.call(cleanup)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Initialize/check an existing Harness database')
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('init', 'doctor', 'migrate-conversations','migrate-context-packs','migrate-parallel-tools'):
        command = commands.add_parser(name)
        command.add_argument('--dsn-env', required=True, help='name of the DSN environment variable, never its value')
        command.add_argument('--durability-profile', choices=['postgresql', 'aurora-postgresql'],
                             default='postgresql', help='explicit operator-verified database storage contract')
        if name in {'migrate-context-packs','migrate-parallel-tools'}: command.add_argument('--store',choices=['workflows','conversations'],required=True)
        if name == 'doctor':
            command.add_argument('--check-write', action='store_true', help='explicit disposable write test; DELETE credentials required')
    commands.choices['init'].add_argument('--parallel-tools',action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.command=='migrate-parallel-tools':
            from .session_store import PostgresSessionStore
            cls=PostgresRunStore if args.store=='workflows' else PostgresSessionStore
            with cls.from_env(args.dsn_env,namespace='parallel-migration',durability_profile=args.durability_profile) as store:store.migrate_parallel_tool_storage()
            print(json.dumps({'migrated':True,'store':args.store,'storage_contract':4 if args.store=='workflows' else 5}))
            return 0
        if args.command=='migrate-context-packs':
            from .session_store import PostgresSessionStore
            cls=PostgresRunStore if args.store=='workflows' else PostgresSessionStore
            with cls.from_env(args.dsn_env,namespace='pack-migration',durability_profile=args.durability_profile) as store:
                store.migrate_context_pack_storage()
            print(json.dumps({'migrated':True,'store':args.store,'storage_contract':2 if args.store=='workflows' else 3}))
            return 0
        if args.command == 'migrate-conversations':
            from .session_store import PostgresSessionStore
            with PostgresSessionStore.from_env(args.dsn_env, namespace='conversation-migration', durability_profile=args.durability_profile) as store:
                store.migrate_context_storage()
            print(json.dumps({'migrated': True, 'conversation_storage_contract': 2}))
            return 0
        namespace = 'prosaic-diagnostic-' + uuid.uuid4().hex
        with PostgresRunStore.from_env(args.dsn_env, namespace=namespace, durability_profile=args.durability_profile) as store:
            if args.command == 'init':
                store.initialize(**({'parallel_tools':True} if args.parallel_tools else {}))
                result = {'initialized': True, 'schema_version': 4 if args.parallel_tools else 1}
            else:
                store.check_ready()
                if args.check_write:
                    check_write(store)
                result = {'ready': True, 'write_checked': args.check_write}
        print(json.dumps(result))
        return 0
    except StoreError as exc:
        result = {'error': exc.code, 'message': str(exc)}
        if args.command == 'doctor' and args.check_write:
            result['diagnostic_namespace'] = namespace
        print(json.dumps(result), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print('{"error":"interrupted","message":"operation interrupted; reconcile before retrying"}', file=sys.stderr)
        return 130
    except Exception:
        print('{"error":"invalid_configuration","message":"check database environment and configuration"}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
