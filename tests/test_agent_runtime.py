import json
import unittest
from apollo_agent import AgentRuntime, Tool, context_message


class RuntimeTests(unittest.TestCase):
    def test_multi_step_inspects_results_before_choosing_next_tool(self):
        decisions = []
        def decide(messages, schema, results):
            decisions.append(results[-1]['tool'] if results else '')
            if not results:
                return {'calls': [{'name': 'calendar', 'arguments': {}}]}
            if len(results) == 1:
                return {'calls': [{'name': 'tasks', 'arguments': {}}]}
            return {'done': True}
        runtime = AgentRuntime([Tool('calendar','Calendar',{},lambda: ['Class at 9']), Tool('tasks','Tasks',{},lambda: ['Essay'])], decide)
        result = runtime.run([])
        self.assertEqual(decisions, ['', 'calendar', 'tasks'])
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(len(result['results']), 2)

    def test_approval_and_validation_fail_closed(self):
        calls = []
        tool = Tool('delete', 'Delete', {'id': {'type':'integer','minimum':1,'maximum':10}}, lambda **args: calls.append(args), ('id',), True)
        agent = AgentRuntime([tool], lambda *_: {'done':True})
        self.assertEqual(agent.call('delete', {'id':1})['status'], 'approval_required')
        self.assertEqual(agent.call('delete', {'id':True})['status'], 'invalid_arguments')
        self.assertEqual(agent.call('delete', {'id':1,'approved':True})['status'], 'invalid_arguments')
        self.assertEqual(agent.call('terminal', {})['status'], 'unknown_tool')
        self.assertEqual(calls, [])

    def test_transient_read_retries_but_mutation_never_replays(self):
        calls = []
        def fail():
            calls.append(1)
            raise TimeoutError()
        read = AgentRuntime([Tool('read','',{},fail)], lambda *_: {})
        self.assertEqual(read.call('read', {})['status'], 'temporary_error')
        self.assertEqual(len(calls), 2)
        write = AgentRuntime([Tool('write','',{},fail, mutation=True, approval=lambda _:True)], lambda *_: {})
        write.call('write', {})
        self.assertEqual(len(calls), 3)
        self.assertEqual(write.call('write', {})['status'], 'duplicate')

    def test_loop_is_bounded_and_trace_omits_private_content(self):
        agent = AgentRuntime([Tool('read','',{},lambda: 'SECRET_USER_DATA')], lambda *_: {'calls':[{'name':'read','arguments':{}}]}, max_steps=3)
        result = agent.run([{'role':'user','content':'SECRET_QUERY'}])
        self.assertEqual(result['status'], 'budget_exhausted')
        self.assertEqual(len(result['results']), 3)
        self.assertNotIn('SECRET', json.dumps(result['trace']))
        self.assertIn('untrusted evidence', context_message(result)['content'])

    def test_error_result_is_not_success(self):
        agent = AgentRuntime([Tool('read','',{},lambda: {'error':'disconnected'})], lambda *_: {'done':True})
        result = agent.run([], [('read',{})])
        self.assertEqual(result['results'][0]['status'], 'failed')
        for response in ({'ok': False}, {'success': False}, {'status': 'failed'}):
            with self.subTest(response=response):
                agent = AgentRuntime([Tool('write', '', {}, lambda: response,
                                           mutation=True, approval=lambda _: True)], lambda *_: {'done': True})
                self.assertEqual(agent.call('write', {})['status'], 'failed')

    def test_empty_search_can_be_reformulated(self):
        queries = []
        def search(query):
            queries.append(query)
            return [] if query == 'dining' else ['Paris restaurant']
        def decide(_m,_s,results):
            return {'done':True} if len(results) == 2 else {'calls':[{'name':'history','arguments':{'query':'Paris'}}]}
        agent = AgentRuntime([Tool('history','',{'query':{'type':'string'}},search,('query',))],decide)
        result = agent.run([], [('history',{'query':'dining'})])
        self.assertEqual(queries, ['dining','Paris'])
        self.assertEqual(result['status'], 'completed')

    def test_tool_status_distinguishes_empty_failure_and_unchecked(self):
        for payload, expected in (
            ({'results': []}, 'empty'),
            ({'status': 'no_results', 'results': []}, 'no_results'),
            ({'status': 'authentication_failure'}, 'authentication_failure'),
            ({'status': 'connected', 'tracks': []}, 'succeeded'),
        ):
            with self.subTest(payload=payload):
                runtime = AgentRuntime([Tool('lookup', '', {}, lambda: payload)], lambda *_: {'done': True})
                self.assertEqual(runtime.call('lookup', {})['status'], expected)
        runtime = AgentRuntime([], lambda *_: {'done': True})
        self.assertEqual(runtime.call('missing', {})['status'], 'unknown_tool')

    def test_invalid_planner_preserves_partial_evidence(self):
        agent = AgentRuntime([Tool('tasks','',{},lambda: ['Essay'])], lambda *_: 'not json')
        result = agent.run([], [('tasks',{})])
        self.assertEqual(result['status'], 'planner_failed')
        self.assertEqual(result['results'][0]['data'], ['Essay'])

    def test_fenced_coordinator_json_is_validated_normally(self):
        agent = AgentRuntime([], lambda *_: '```json\n{"calls":[],"done":true}\n```')
        self.assertEqual(agent.run([])['status'], 'completed')


if __name__ == '__main__': unittest.main()
