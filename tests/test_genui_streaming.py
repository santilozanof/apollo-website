import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_node(source):
    result = subprocess.run(
        ["node", "-e", source],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


class GenerativeUIStreamingTests(unittest.TestCase):
    def test_katex_supports_required_technical_notation(self):
        expressions = [
            r"\frac{d}{dx}x^2=2x",
            r"\lim_{x\to 0}\frac{\sin x}{x}=1",
            r"\int_0^1 x^2\,dx=\frac13",
            r"\begin{bmatrix}1&2\\3&4\end{bmatrix}",
            r"f(x)=\begin{cases}x^2&x\ge0\\-x&x<0\end{cases}",
        ]
        script = """
const katex = require('./vendor/katex/katex.min.js');
const expressions = %s;
for (const value of expressions) {
  const html = katex.renderToString(value, {throwOnError: true, output: 'htmlAndMathml'});
  if (!html.includes('katex-mathml') || !html.includes('katex-html')) process.exit(2);
}
console.log(expressions.length);
""" % json.dumps(expressions)
        self.assertEqual(run_node(script), str(len(expressions)))

    def test_arbitrary_chunk_boundaries_never_emit_incomplete_blocks(self):
        source = (
            "# Calculus\n\n"
            "The derivative is \\(f'(x)=2x\\).\n\n"
            "\\[\n\\int_0^1 x^2\\,dx=\\frac{1}{3}\n\\]\n\n"
            "| x | f(x) |\n|---:|---:|\n| 2 | \\(4\\) |\n\n"
            "```python\nprint('safe')\n```\n\n"
            "```apollo-ui\n{\"blocks\":[{\"type\":\"status\",\"id\":\"ok\",\"text\":\"Done\"}]}\n```"
        )
        script = """
const gen = require('./apollo_genui.js');
const source = %s;
let previous = [];
for (let i = 1; i <= source.length; i += 1) {
  const current = gen.completeStreamSegments(source.slice(0, i), false).segments;
  if (current.length < previous.length) process.exit(2);
  for (let j = 0; j < previous.length; j += 1) {
    if (current[j] !== previous[j]) process.exit(3);
  }
  for (const block of current) {
    if (block.startsWith('```') && !block.trimEnd().endsWith('```')) process.exit(4);
    if (block.startsWith('\\\\[') && !block.trimEnd().endsWith('\\\\]')) process.exit(5);
  }
  previous = current;
}
const finalBlocks = gen.completeStreamSegments(source, true).segments;
if (finalBlocks.join('\\n\\n') !== source) process.exit(6);
console.log(finalBlocks.length);
""" % json.dumps(source)
        self.assertEqual(run_node(script), "6")

    def test_incomplete_inline_and_ui_syntax_stays_buffered(self):
        script = r"""
const gen = require('./apollo_genui.js');
const cases = [
  'Work: \\(\\frac{1}{2}',
  'A **partial',
  '[unfinished](https://example.com',
  '```apollo-ui\n{"blocks":[{"type":"status"}]}'
];
for (const value of cases) {
  if (gen.completeStreamSegments(value, false).segments.length) process.exit(2);
}
console.log('buffered');
"""
        self.assertEqual(run_node(script), "buffered")

    def test_prompt_requires_consistent_math_and_complete_blocks(self):
        server = (ROOT / "server.py").read_text()
        self.assertIn("valid KaTeX-compatible LaTeX", server)
        self.assertIn(r"Use \(...\) for inline math", server)
        self.assertIn("Always close every math delimiter", server)
        self.assertIn("fully closed fenced blocks", server)

    def test_live_stream_paths_use_stateful_renderer(self):
        page = (ROOT / "index.html").read_text()
        self.assertEqual(page.count("createStreamRenderer?.("), 2)
        self.assertEqual(page.count("apolloStreamRenderer.update(assistantContent)"), 2)
        self.assertEqual(page.count("apolloStreamRenderer?.finish(assistantContent)"), 2)
        self.assertIn('src="/vendor/katex/katex.min.js?v=0.19.0"', page)
        retry_start = page.index("async function apolloRetryMessage")
        retry_end = page.index("function apolloGetClientContext", retry_start)
        retry = page[retry_start:retry_end]
        self.assertIn("const requestChatId = apolloChatId;", retry)
        self.assertIn("`/api/chats/${requestChatId}/messages`", retry)
        self.assertIn("apolloShowTyping(\n            userMessage,", retry)
        self.assertNotIn("isImageGeneration", retry)
        self.assertNotIn("hasAttachments", retry)

    def test_quiz_content_uses_the_same_math_renderer(self):
        client = (ROOT / "apollo_genui.js").read_text()
        self.assertIn("appendInline(questionNode, question.question)", client)
        self.assertIn("appendInline(optionButton, option.label)", client)
        self.assertIn("appendInline(feedback, correctOption?.explanation", client)


if __name__ == "__main__":
    unittest.main()
