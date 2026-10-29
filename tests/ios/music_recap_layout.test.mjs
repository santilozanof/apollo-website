import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';

const source = readFileSync(new URL('../../apollo_music_insights.js', import.meta.url), 'utf8');
const renderer = source.slice(source.indexOf('  const recapSizes = '), source.indexOf('  function canvasBlob('));

function context(calls) {
  return {
    fillStyle: '', font: '40px system-ui', textAlign: 'left',
    fillRect() {}, fill() {}, beginPath() {}, roundRect() {}, arc() {}, clip() {}, save() {}, restore() {},
    createLinearGradient() { return {addColorStop() {}}; },
    createRadialGradient() { return {addColorStop() {}}; },
    drawImage(image) { calls.images.push(image.id); },
    getImageData() { return {data: new Uint8ClampedArray(16 * 16 * 4).fill(90)}; },
    measureText(value) { return {width: String(value).length * (Number(this.font.match(/(\d+)px/)?.[1]) || 40) * .52}; },
    fillText(value, x, y) { calls.text.push({value, x, y}); },
  };
}

test('weekly and monthly recap canvases retain matched art, five ranks and export dimensions across all themes', async () => {
  const tracks = Array.from({length: 5}, (_, index) => ({name: `Track ${index + 1} with a very long descriptive title`, artist_name: `Artist ${index + 1}`, image_url: `https://i.scdn.co/image/track${index}`}));
  const artists = Array.from({length: 5}, (_, index) => ({name: `Artist ${index + 1}`, image_url: `https://i.scdn.co/image/artist${index}`}));
  const calls = {text: [], images: []};
  const state = {recap: {period: {label: 'Sep 1 – Sep 7, 2026'}, top: {tracks, artists}, events: 87, verified_ms: 7200000, estimated_ms: 0}, slide: 0, theme: 'noir', format: 'story'};
  const sandbox = {state, document: {createElement() {return {width: 16, height: 16, getContext() {return context(calls);}};}}, safeArt: () => true,
    artImage: async url => ({id: url, width: 500, height: 500}), brandImage: async () => ({id: 'spotify', width: 200, height: 60}), duration: () => '2h 0m'};
  runInNewContext(`${renderer}\nthis.renderRecap = renderRecap;`, sandbox);
  for (const theme of ['noir', 'atmosphere', 'editorial', 'after-hours']) {
    for (const [format, height] of [['story', 1920], ['portrait', 1350], ['square', 1080]]) {
      for (const slide of [0, 1, 2]) {
        calls.text.length = calls.images.length = 0;
        const canvas = {getContext() {return context(calls);}};
        await sandbox.renderRecap(canvas, {theme, format, slide});
        assert.equal(canvas.width, 1080);
        assert.equal(canvas.height, height);
        assert.ok(calls.text.every(item => item.x >= 0 && item.x <= 1080 && item.y >= 0 && item.y < height), `${theme}/${format}/${slide} text bounds`);
        assert.ok(calls.images.includes('spotify'), `${theme}/${format}/${slide} attribution`);
        if (slide === 0) {
          assert.ok(calls.images.includes(tracks[0].image_url));
          assert.ok(calls.images.includes(artists[0].image_url));
          assert.ok(calls.text.some(item => item.value === '87'));
        } else {
          const expected = slide === 1 ? tracks : artists;
          for (const item of expected) assert.ok(calls.images.includes(item.image_url), `${theme}/${format}/${slide}: ${item.image_url}`);
          if (slide === 1 && format === 'square') assert.ok(calls.text.some(item => item.value.includes('descriptive title')), 'long track titles wrap within the square layout');
        }
      }
    }
  }
  sandbox.artImage = async url => url === tracks[0].image_url ? null : {id: url, width: 500, height: 500};
  calls.text.length = calls.images.length = 0;
  await sandbox.renderRecap({getContext() {return context(calls);}}, {theme: 'noir', format: 'story', slide: 0});
  assert.ok(calls.images.includes(tracks[1].image_url), 'next available artwork is used');
  assert.ok(calls.text.some(item => item.value.startsWith('Track 2')), 'featured label matches the artwork');
});
