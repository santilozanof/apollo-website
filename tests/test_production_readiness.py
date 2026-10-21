import sqlite3
import unittest
from unittest.mock import patch
from tests import test_memory_intelligence as memory_fixture
from apollo_web_extract import destination, collection_links


class BackfillTests(unittest.TestCase):
    setUp = memory_fixture.MemoryTests.setUp
    db = memory_fixture.MemoryTests.db
    chat = memory_fixture.MemoryTests.chat
    message = memory_fixture.MemoryTests.message
    def test_embedding_backfill_is_resumable_and_does_not_consume_fact_jobs(self):
        first = self.message('A bistro by the river.', date='2026-01-01')
        second = self.message('The restaurant is in Paris.', date='2026-02-01')
        with self.db() as conn:
            before = [tuple(r) for r in conn.execute('SELECT * FROM messages ORDER BY id')]
        self.assertEqual(self.store.index_pending(batch=1), 1)
        self.assertEqual(self.store.index_pending(batch=1), 1)
        self.assertEqual(self.store.index_pending(batch=1), 0)
        with self.db() as conn:
            self.assertEqual(before, [tuple(r) for r in conn.execute('SELECT * FROM messages ORDER BY id')])
            self.assertEqual(conn.execute('SELECT sum(consolidated) FROM memory_jobs').fetchone()[0], 0)
            self.assertEqual(conn.execute('SELECT count(*) FROM message_embeddings').fetchone()[0], 2)
        self.assertEqual(self.store.search('Paris dining')['mode'], 'hybrid')

    def test_backfill_rechecks_deletion_after_encode(self):
        mid = self.message('A restaurant in Paris')
        original = self.store.embeddings.encode
        def encode(texts):
            with self.db() as conn:
                conn.execute('DELETE FROM messages WHERE id=?', (mid,))
            return original(texts)
        self.store.embeddings.encode = encode
        self.store.index_pending()
        with self.db() as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM message_embeddings').fetchone()[0], 0)

    def test_consolidation_can_run_without_embedding_again(self):
        self.message('I prefer a restaurant in Paris')
        self.store.index_pending()
        with patch.object(self.store.embeddings, 'encode', side_effect=AssertionError('duplicate embedding')):
            self.store.process_pending(lambda *_: [], indexing=False)
        with self.db() as conn:
            self.assertEqual(conn.execute('SELECT consolidated FROM memory_jobs').fetchone()[0], 1)


class DestinationTests(unittest.TestCase):
    def test_planning_look_like_does_not_request_photographs(self):
        from apollo_media import visual_request
        for prompt in ['What does tomorrow look like for me, and which unfinished assignments should I tackle in the available gaps?',
                       'What does my workload look like for the week?', 'What does my schedule look like for tomorrow?']:
            self.assertIsNone(visual_request(prompt))
        self.assertEqual(visual_request('What does FL Studio look like?'), 'fl-studio')
        self.assertEqual(visual_request('Show me photos of a vintage espresso machine.'), 'vintage espresso machine')

    def test_explicit_short_requests_bypass_silence_classifier(self):
        import server
        for prompt in ['Convert 90 minutes to hours. Answer briefly.', 'Give a one-sentence definition of an octave.',
                       'Name the three primary colors of light.', 'Please summarize this paragraph.']:
            with patch.object(server, 'ask_hermes', side_effect=AssertionError('unnecessary classifier')):
                self.assertTrue(server.apollo_should_reply_semantically([], prompt))
        self.assertTrue(server.apollo_silence_candidate('Thanks, that helps'))

    def test_private_mixed_dns_and_credentials_rejected(self):
        for url in ['file:///etc/passwd', 'https://user:pass@example.com/', 'http://example.com:8765']:
            with self.assertRaises(ValueError):
                destination(url)
        for addresses in [['127.0.0.1'], ['169.254.169.254'], ['100.64.0.1'], ['8.8.8.8', '10.0.0.1'], ['::1']]:
            with patch('socket.getaddrinfo', return_value=[(2, 1, 6, '', (ip, 443)) for ip in addresses]):
                with self.assertRaises(ValueError):
                    destination('https://example.com')

    def test_public_address_is_pinned(self):
        with patch('socket.getaddrinfo', return_value=[(2, 1, 6, '', ('8.8.8.8', 443))]):
            self.assertEqual(destination('https://example.com/path')[1:], ('example.com', 443, '8.8.8.8'))

class ExtractionEvidenceTests(unittest.TestCase):
    def test_current_release_checks_linked_index_not_only_old_announcement(self):
        from tests.test_live_research_pipeline import response, FakeHTTP
        import apollo_live_research as live
        old = 'https://www.ufc.com/events'
        index = 'https://www.ufc.com/releases/'
        result = response(answer='Version 1 [release]('+old+')')
        def extract(url):
            return {'url':url,'content':'Version 2 is the latest stable release' if url==index else 'Version 1 was released last year',
                    'index_links':[] if url==index else [index]}
        def opener(req,**kwargs):
            import json
            pages=json.loads(json.loads(req.data)['messages'][1]['content'])['retrieved_pages']
            self.assertTrue(any(p.get('freshness_index') and 'Version 2' in p['content'] for p in pages))
            return FakeHTTP({'choices':[{'finish_reason':'stop','message':{'content':'Version 2 [release index]('+index+')'}}]})
        with patch.dict('os.environ',{'APOLLO_WEB_EXTRACT_BACKEND':'trafilatura'}),patch('apollo_web_extract.extract_page',side_effect=extract):
            augmented=live._extract_and_synthesize(result,'What is the current release?','instruction','test','http://localhost',opener)
        self.assertEqual(live._inspect_response(augmented)[0],'succeeded')
        self.assertIn(index,live._source_evidence(augmented)[0])

    def test_collection_navigation_uses_observed_same_origin_links(self):
        html='<a href="/downloads/">Downloads</a><a href="/releases/">Releases</a><a href="http://127.0.0.1/news">bad</a>'
        self.assertEqual(collection_links(html,'https://example.com/release/v1'),['https://example.com/downloads/','https://example.com/releases/'])

    def test_available_calendar_gaps_are_not_product_research(self):
        import apollo_live_research as live
        self.assertIsNone(live.live_query_kind('What does tomorrow look like for me, and which unfinished assignments should I tackle in the available gaps? Make a practical plan without changing anything.'))
        self.assertIsNone(live.live_query_kind('Which unfinished assignments can fit in my available time?'))
        self.assertEqual(live.live_query_kind('What is the current price of this product?'), 'current')

    def test_local_pages_are_used_for_synthesis_and_citations(self):
        from tests.test_live_research_pipeline import response, FakeHTTP
        import apollo_live_research as live
        result = response(answer='A claim [source](https://www.ufc.com/events)')
        pages = {'url':'https://www.ufc.com/events','resolved_url':'https://www.ufc.com/events','content':'Verified page text ' * 20}
        def opener(req, **kw):
            import json
            body = json.loads(req.data)
            self.assertTrue(body['model_options']['disable_tools'])
            self.assertIn('Verified page text', body['messages'][1]['content'])
            return FakeHTTP({'choices':[{'finish_reason':'stop','message':{'content':'Supported claim [source](https://www.ufc.com/events)'}}]})
        with patch.dict('os.environ', {'APOLLO_WEB_EXTRACT_BACKEND':'trafilatura'}), patch('apollo_web_extract.extract_page',return_value=pages):
            augmented = live._extract_and_synthesize(result,'question','instruction','test','http://localhost/v1/chat/completions',opener)
        self.assertTrue(live._source_evidence(augmented)[1])
        self.assertEqual(live._inspect_response(augmented)[0], 'succeeded')

    def test_extraction_failure_does_not_claim_page_evidence(self):
        from tests.test_live_research_pipeline import response
        import apollo_live_research as live
        result = response()
        with patch.dict('os.environ', {'APOLLO_WEB_EXTRACT_BACKEND':'trafilatura'}), patch('apollo_web_extract.extract_page',return_value={'error':'http_403'}):
            augmented = live._extract_and_synthesize(result,'question','instruction','test','http://localhost',lambda *_:self.fail('must not synthesize'))
        self.assertFalse(live._source_evidence(augmented)[1])
