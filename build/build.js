/*
 * Builds index.html (deployed) from src/uri.html (edited).
 *
 *   node build/build.js
 *
 * What it does, and why each step exists:
 *   1. Pulls the JSX out of src/uri.html and compiles it ahead of time, so the
 *      2.4MB in-browser Babel runtime never ships.
 *   2. Escapes every non-ASCII character to \uXXXX. The page must survive being
 *      served without a charset header -- otherwise em dashes and "o-umlaut"
 *      turn to mojibake. Pure ASCII is immune to that regardless of the host.
 *   3. Inlines React, Tailwind and the three typefaces, so the page has zero
 *      external requests and renders identically offline.
 */
const fs = require('fs');
const path = require('path');

const ROOT   = path.join(__dirname, '..');
const VENDOR = path.join(__dirname, 'vendor');
const SRC    = path.join(ROOT, 'src', 'uri.html');
const OUT    = path.join(ROOT, 'index.html');

const read = p => fs.readFileSync(p, 'utf8');
const Babel = require(path.join(VENDOR, 'babel.js'));

const src = read(SRC);

/* ---- 1. compile the JSX ---------------------------------------------------- */
const open = src.indexOf('<script type="text/babel"');
const bodyStart = src.indexOf('>', open) + 1;
const bodyEnd = src.indexOf('</script>', bodyStart);
let jsx = src.slice(bodyStart, bodyEnd);

// jsesc only escapes string literals, so the one regex holding non-ASCII is
// escaped here rather than after compilation.
jsx = jsx.replace(/\/\[\\s[^\/]*\]\+\//, m =>
  m.replace(/[^\x00-\x7F]/g, c => '\\u' + c.charCodeAt(0).toString(16).padStart(4, '0')));

let app = Babel.transform(jsx, {
  presets: [['react', { runtime: 'classic' }]],
  comments: false,
  compact: false,
}).code;

/* ---- 2. make it pure ASCII ------------------------------------------------- */
app = app.replace(/[^\x00-\x7F]/g, c => '\\u' + c.charCodeAt(0).toString(16).padStart(4, '0'));

try {
  Babel.transform(app, { presets: [] });
} catch (e) {
  console.error('build failed: compiled output does not parse\n' + e.message);
  process.exit(1);
}

/* ---- 3. inline everything -------------------------------------------------- */
let css = src.match(/<style>([\s\S]*?)<\/style>/)[1];
css = css.replace(/[^\x00-\x7F]/g, '-');              // box-drawing chars in comments
const twConfig = src.match(/<script>\s*(tailwind\.config[\s\S]*?)<\/script>/)[1];

const doc = [
  '<title>Undergraduate Research Incubator</title>',
  '<style>\n' + read(path.join(VENDOR, 'fonts-inline.css')) + '\n' + css + '\n</style>',
  '<script>' + read(path.join(VENDOR, 'tailwind.js')) + '</script>',
  '<script>' + twConfig + '</script>',
  '<div id="root"></div>',
  '<script>' + read(path.join(VENDOR, 'react.js')) + '</script>',
  '<script>' + read(path.join(VENDOR, 'react-dom.js')) + '</script>',
  '<script>' + app + '</script>',
].join('\n');

/* ---- 4. refuse to ship a broken build -------------------------------------- */
const problems = [];
if (/[^\x00-\x7F]/.test(doc))                  problems.push('non-ASCII characters present');
if (/(?:src|href)="https?:/.test(doc))         problems.push('external resource reference present');
if (doc.indexOf('<title>') > 8192)             problems.push('<title> past the 8KB scan window');
if (problems.length) {
  console.error('build failed:\n  - ' + problems.join('\n  - '));
  process.exit(1);
}

fs.writeFileSync(OUT, doc, 'ascii');
console.log('built index.html  ' + (fs.statSync(OUT).size / 1048576).toFixed(2) + ' MB');
console.log('  pure ASCII, zero external requests');
