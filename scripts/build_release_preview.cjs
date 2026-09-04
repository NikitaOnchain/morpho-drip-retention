#!/usr/bin/env node
/* Local QA-only Markdown rendering. No server, deployment or external resource.
 * Requires Node.js and marked 17.0.5 (resolved from NODE_PATH if needed).
 * Writes only ignored previews and a compact build receipt; sources unchanged.
 */
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { pathToFileURL } = require('node:url');
const { marked } = require('marked');
const root = path.resolve(__dirname, '..');
const out = path.join(root, 'data/tmp/phase8_markdown_preview');
const files = ['README.md', 'reports/DRIP_LENDING_DEMAND_REPORT.md',
  'docs/REPRODUCTION.md', 'docs/HEADLINE_PROVENANCE.md', 'docs/RELEASE_LIMITATIONS.md',
  'docs/REVIEWER_BRIEF.md', 'docs/RELEASE_CHECKLIST.md',
  'docs/RELEASE_CANDIDATE_QA.md', 'reports/DISTRIBUTION_DRAFTS.md'];
const sha = b => crypto.createHash('sha256').update(b).digest('hex');
fs.mkdirSync(out, { recursive: true });
const rows = [];
for (const rel of files) {
  const source = fs.readFileSync(path.join(root, rel));
  let body = marked.parse(source.toString('utf8'), { gfm: true });
  const images = [];
  body = body.replace(/<img src="([^"]+)" alt="([^"]*)"[^>]*>/g, (_, src, alt) => {
    if (/^[a-z]+:/i.test(src)) throw new Error('Remote image not allowed');
    if (!alt.trim()) throw new Error('Empty alt text');
    const local = path.resolve(root, path.dirname(rel), src);
    const image = fs.readFileSync(local);
    if (image.subarray(0, 8).toString('hex') !== '89504e470d0a1a0a') throw new Error('Expected PNG');
    images.push({ path: path.relative(root, local).replaceAll('\\', '/'), sha256: sha(image),
      width: image.readUInt32BE(16), height: image.readUInt32BE(20) });
    return `<img src="data:image/png;base64,${image.toString('base64')}" alt="${alt}">`;
  });
  // Absolute file URLs exist in ignored QA previews only, never public Markdown.
  body = body.replace(/href="([^"#][^"]*)"/g, (_, href) => /^[a-z]+:/i.test(href)
    ? `href="${href}"` : `href="${pathToFileURL(path.resolve(root, path.dirname(rel), href)).href}"`);
  const html = `<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'">
<title>${path.basename(rel)} — local release preview</title><style>
body{max-width:1100px;margin:40px auto;padding:0 28px;font:17px/1.65 system-ui,sans-serif;color:#17222c;background:white}
h1{font-size:34px;line-height:1.2}h2{font-size:25px;margin-top:38px;line-height:1.3}a{color:#125da8}
img{display:block;width:100%;height:auto;margin:24px 0}pre{overflow:auto;padding:16px;background:#f2f5f7;font-size:14px}
code{font-size:.9em}table{border-collapse:collapse;display:block;overflow:auto}td,th{border:1px solid #ccc;padding:8px;vertical-align:top}
</style><main>${body}</main></html>`;
  const name = rel.replaceAll('/', '__') + '.html';
  fs.writeFileSync(path.join(out, name), html);
  rows.push({ source: rel, source_sha256: sha(source), preview: 'data/tmp/phase8_markdown_preview/' + name,
    headings: (body.match(/<h[1-6]>/g) || []).length, images });
}
if (rows[0].images.length !== 6) throw new Error('README must contain six accepted figures');
const drafts = fs.readFileSync(path.join(root, 'reports/DISTRIBUTION_DRAFTS.md'), 'utf8');
const xSection = drafts.split('## X thread')[1].split('## LinkedIn')[0];
const xLengths = [...xSection.matchAll(/^\d\. (.+)$/gm)].map(m => [...m[1]].length);
const receipt = { status: 'PASS', scope: 'local static Markdown build; not GitHub-renderer parity or browser review',
  node_version: process.version, marked_version: require('marked/package.json').version,
  external_requests: 0, files: rows, x_draft_codepoint_lengths: xLengths,
  note: 'X drafts still require final platform length review after alias/URL substitution.' };
fs.mkdirSync(path.join(root, 'data/release'), { recursive: true });
fs.writeFileSync(path.join(root, 'data/release/phase8_markdown_build.json'), JSON.stringify(receipt, null, 2) + '\n');
console.log(JSON.stringify({ status: receipt.status, pages: rows.length, figures: rows[0].images.length,
  node: receipt.node_version, marked: receipt.marked_version, x_draft_codepoint_lengths: xLengths }));
