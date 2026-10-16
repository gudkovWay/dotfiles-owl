import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { createServer } from 'node:http';
import { mkdtemp, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { test } from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { promisify } from 'node:util';

const execute = promisify(execFile);
const opener = process.env.OMP_OPENER_UNDER_TEST ??
  fileURLToPath(new URL('../omp/herdr-local-files/open-file.ts', import.meta.url));
const png = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aZ1cAAAAASUVORK5CYII=',
  'base64',
);

test('dotfiles image opener preserves native application dispatch', { timeout: 15000 }, async (t) => {
  const directory = await mkdtemp(path.join(tmpdir(), 'dotfiles-image-opener-'));
  const output = path.join(directory, 'opened');
  await writeFile(path.join(directory, 'xdg-open'),
    '#!/bin/sh\nprintf "%s" "$1" > "$OMP_OPEN_RESULT"\n', { mode: 0o700 });
  const requests = [];
  const server = createServer((request, response) => {
    requests.push(request.url);
    if (request.url === '/missing.png') {
      response.writeHead(404);
      response.end();
    } else if (request.url === '/wrong.png') {
      response.writeHead(200, { 'Content-Type': 'text/html' });
      response.end('<html/>');
    } else if (request.url === '/large.png') {
      response.writeHead(200, { 'Content-Type': 'image/png', 'Content-Length': '33554433' });
      response.end(Buffer.alloc(33554433));
    } else {
      response.writeHead(200, { 'Content-Type': 'image/png' });
      response.end(png);
    }
  });
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolve);
  });
  const base = `http://127.0.0.1:${server.address().port}`;

  async function run(target, kitty = false) {
    await rm(output, { force: true });
    try {
      await execute('bun', [opener, ...(kitty ? [target] : [])], {
        env: {
          ...process.env,
          PATH: `${directory}:${process.env.PATH}`,
          TMPDIR: directory,
          OMP_OPEN_RESULT: output,
          HERDR_PLUGIN_CLICKED_URL: kitty ? '' : target,
        },
        timeout: 5000,
      });
      return 0;
    } catch (error) {
      if (typeof error.code !== 'number') throw error;
      return error.code;
    }
  }

  try {
    await t.test('Herdr remote image clicks open local image bytes, not the HTTPS handler', async () => {
      assert.equal(await run(`${base}/image.PNG?download=1#preview`), 0);
      const opened = await readFile(output, 'utf8');
      assert.equal(path.isAbsolute(opened), true);
      assert.equal(path.extname(opened), '.png');
      assert.deepEqual(await readFile(opened), png);
      assert.deepEqual(requests, ['/image.PNG?download=1']);
    });

    await t.test('Kitty web pages remain URLs without downloading them', async () => {
      assert.equal(await run(`${base}/article?cover=picture.png`, true), 0);
      assert.equal(await readFile(output, 'utf8'), `${base}/article?cover=picture.png`);
      assert.deepEqual(requests, ['/image.PNG?download=1']);
    });

    await t.test('registered application protocols keep their native handler', async () => {
      assert.equal(await run('mailto:example@example.com', true), 0);
      assert.equal(await readFile(output, 'utf8'), 'mailto:example@example.com');
    });

    await t.test('local image names are decoded and location hints excluded', async () => {
      const image = path.join(directory, 'файл #.png');
      await writeFile(image, png);
      assert.equal(await run(`${pathToFileURL(image).href}?line=12#preview`), 0);
      assert.equal(await readFile(output, 'utf8'), image);
      await rm(image);
    });

    await t.test('HTTP failures, non-images and oversized responses do not launch a viewer', async () => {
      const before = (await readdir(directory)).filter(name => name !== 'opened').sort();
      for (const route of ['/missing.png', '/wrong.png', '/large.png']) {
        assert.equal(await run(`${base}${route}`), 1, route);
        await assert.rejects(readFile(output), { code: 'ENOENT' });
        assert.deepEqual((await readdir(directory)).sort(), before);
      }
    });

    await t.test('remote file authorities and control bytes cannot reach the native opener', async () => {
      for (const target of ['file://remote/tmp/image.png', 'file:///tmp/%00image.png']) {
        assert.equal(await run(target), 1);
        await assert.rejects(readFile(output), { code: 'ENOENT' });
      }
    });
  } finally {
    server.closeAllConnections();
    await new Promise(resolve => server.close(resolve));
    await rm(directory, { recursive: true, force: true });
  }
});
