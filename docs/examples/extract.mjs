// Sends a file to the eCode API and prints the barcodes found. Node.js 18 or later (no package to install).
//
//     node extract.mjs document.pdf
//     node extract.mjs photo.jpg --thorough
//
// Settings (environment variables):
//     ECODE_URL   address of the service                          (default http://localhost:5000)
//     ECODE_KEY   your API key, the one that starts with ecode_   (required)
import { readFile } from 'node:fs/promises';
import { basename } from 'node:path';

const URL_BASE = (process.env.ECODE_URL ?? 'http://localhost:5000').replace(/\/$/, '');
const KEY = process.env.ECODE_KEY;

/** Returns the JSON answer of the service; throws an Error carrying the service's message otherwise. */
async function extract(path, thorough = false) {
  const form = new FormData();
  form.append('file', new Blob([await readFile(path)]), basename(path));

  const response = await fetch(`${URL_BASE}/api/v1/extract${thorough ? '?thorough=1' : ''}`, {
    method: 'POST',
    headers: { 'X-API-Key': KEY },          // do not set Content-Type: fetch adds it, with the multipart boundary
    body: form,
    signal: AbortSignal.timeout(60_000),
  });
  const body = await response.json();
  // Every error answer is {"error": "message"}; 429 means the quota of the key is used up
  if (!response.ok) throw new Error(`${response.status}: ${body.error}`);
  return body;
}

const [file, ...flags] = process.argv.slice(2);
if (!KEY || !file) {
  console.error('usage: ECODE_KEY=ecode_... node extract.mjs <file.pdf|.png|.jpg> [--thorough]');
  process.exit(1);
}

try {
  const result = await extract(file, flags.includes('--thorough'));
  console.log(`${result.file_type}, ${result.page_count} page(s), ${result.barcodes.length} code(s)`);
  for (const code of result.barcodes) {
    const { x, y, w, h } = code.coordinates;
    console.log(`  page ${code.page}  ${code.type.padEnd(10)} ${code.data}   at (${x}, ${y}) ${w}x${h}`);
  }
  for (const region of result.unread_regions) {
    console.log(`  page ${region.page}  region that looks like a code but could not be read (confidence ${region.score})`);
  }
} catch (error) {
  console.error(`Error ${error.message}`);
  process.exit(1);
}
