import json
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"
SERVER = ROOT / "server.py"


class MusicProgressRegressionTests(unittest.TestCase):
    def reconciler_source(self):
        source = INDEX.read_text(encoding="utf-8")
        start = source.index("// APOLLO_MUSIC_PROGRESS_RECONCILER_START")
        end = source.index("// APOLLO_MUSIC_PROGRESS_RECONCILER_END")
        return source[start:end]

    def run_reconciler_scenario(self):
        if not shutil.which("node"):
            self.skipTest("Node.js is unavailable")
        scenario = r"""
let now = 1000000;
let playing = true;
let anchor = reconcilePlaybackProgress({
  localProgress: 0, incomingProgress: 0, playing: true,
  sampledAt: now, now, hardSync: true
});
let anchorTime = now;
const live = at => anchor + (playing ? at - anchorTime : 0);
const observed = [];

// Six normal five-second polls cover uninterrupted playback for 30 seconds.
for (let seconds = 1; seconds <= 30; seconds += 1) {
  now += 1000;
  observed.push(live(now));
  if (seconds % 5 === 0) {
    const localProgress = live(now);
    anchor = reconcilePlaybackProgress({
      localProgress,
      incomingProgress: seconds * 1000 - 150,
      playing: true,
      sampledAt: now - 150,
      now,
      hardSync: false
    });
    anchorTime = now;
  }
}

const uninterrupted = {
  monotonic: observed.every((value, index) => index === 0 || value >= observed[index - 1]),
  final: live(now),
  minimumAfterPoll: Math.min(...observed.slice(5))
};

// Pause, resume, external seek, track change, and device change all hard-sync.
let localProgress = live(now);
playing = false;
anchor = reconcilePlaybackProgress({localProgress, incomingProgress: 30000, playing, sampledAt: now, now, hardSync: true});
anchorTime = now;
now += 3000;
const paused = live(now);

playing = true;
anchor = reconcilePlaybackProgress({localProgress: paused, incomingProgress: 30000, playing, sampledAt: now, now, hardSync: true});
anchorTime = now;
now += 1000;
const resumed = live(now);

anchor = reconcilePlaybackProgress({localProgress: resumed, incomingProgress: 60000, playing, sampledAt: now, now, hardSync: false});
anchorTime = now;
const sought = live(now);

anchor = reconcilePlaybackProgress({localProgress: sought, incomingProgress: 1000, playing, sampledAt: now, now, hardSync: true});
anchorTime = now;
const changedTrack = live(now);

anchor = reconcilePlaybackProgress({localProgress: changedTrack, incomingProgress: 2000, playing, sampledAt: now, now, hardSync: true});
anchorTime = now;
const changedDevice = live(now);

console.log(JSON.stringify({uninterrupted, paused, resumed, sought, changedTrack, changedDevice}));
"""
        result = subprocess.run(
            ["node", "-e", self.reconciler_source() + "\n" + scenario],
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(result.stdout)

    def test_progress_is_smooth_for_thirty_seconds_and_handles_state_changes(self):
        result = self.run_reconciler_scenario()
        self.assertTrue(result["uninterrupted"]["monotonic"])
        self.assertGreaterEqual(result["uninterrupted"]["final"], 30000)
        self.assertGreater(result["uninterrupted"]["minimumAfterPoll"], 0)
        self.assertEqual(result["paused"], 30000)
        self.assertEqual(result["resumed"], 31000)
        self.assertEqual(result["sought"], 60000)
        self.assertEqual(result["changedTrack"], 1000)
        self.assertEqual(result["changedDevice"], 2000)

    def test_backend_and_frontend_preserve_authoritative_spotify_position(self):
        server = SERVER.read_text(encoding="utf-8")
        spotify_tool = (SERVER.parent / "spotify_curator_tool.py").read_text(encoding="utf-8")
        index = INDEX.read_text(encoding="utf-8")
        self.assertIn('"progress_ms": data.get("progress_ms")', server)
        self.assertIn('"progress_ms": player.get("progress_ms") or 0', server)
        self.assertIn('"sampled_at_ms": int(time.time() * 1000)', spotify_tool)
        self.assertIn("reconcilePlaybackProgress({", index)
        self.assertIn("|| trackChanged", index)
        self.assertIn("|| deviceChanged", index)
        self.assertIn("|| playStateChanged", index)
        self.assertIn('progressTrack.addEventListener("click"', index)
        self.assertIn('spotifyControl("seek", Math.round(nextPosition))', index)
        self.assertIn('position_ms:', index)

    def test_music_view_reuses_the_single_global_poll(self):
        source = INDEX.read_text(encoding="utf-8")
        music_start = source.index("APOLLO MUSIC — NOW PLAYING V1", 38000)
        music_end = source.index("APOLLO MUSIC — TRANSPORT CONTROL POLISH", music_start)
        music = source[music_start:music_end]
        self.assertIn("pollTimer =", music)
        self.assertNotIn("if (musicVisible) {\n                        loadNowPlaying();", music)
        self.assertIn('window.addEventListener("apollo:spotify-playback"', music)
        self.assertIn("progressTimer =", music)
        self.assertIn("500", music)


if __name__ == "__main__":
    unittest.main()
