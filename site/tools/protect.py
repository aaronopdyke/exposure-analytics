"""Publish the site HTML behind a landing page (open by default).

Default (no flags): docs/index.html becomes the branded landing page with a
single "Enter the explorer" button (the explorer HTML is embedded and swapped
in on click - no password, no crypto); every other page is copied to docs/
as-is.

Optional legacy modes:
  py site/tools/protect.py --password X   # AES-256-GCM password gate on all
                                          # pages (StatiCrypt-equivalent;
                                          # needs pip install cryptography)
  py site/tools/protect.py --plain        # no landing at all: plain copies

Note: everything under docs/data/ and docs/assets/ is always fetchable by
direct URL. Do not publish sensitive data.
"""

import argparse
import base64
import hashlib
import os
import shutil
import sys

SITE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(SITE)
PAGES = os.path.join(SITE, 'pages')
DOCS = os.path.join(REPO, 'docs')   # GitHub Pages serves main:/docs
ITERATIONS = 310_000

TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Exposure Comparison</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Ctext y='.9em' font-size='90'%3E%F0%9F%8F%A2%3C/text%3E%3C/svg%3E">
<style>
  :root { --navy:#17406D; --blue:#0F6FC6; --bright:#009DD9; --cyan:#0BD0D9; }
  * { box-sizing: border-box; }
  body { margin:0; min-height:100vh; display:flex; align-items:center;
         justify-content:center; overflow:hidden; color:#eaf3fb;
         font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;
         background:radial-gradient(120% 140% at 78% 18%, #0F6FC6 0%,
                    #17406D 42%, #0b1f3a 100%); }
  #field { position:fixed; inset:0; width:100vw; height:100vh; z-index:0; }
  .cell { animation: pulse 7s ease-in-out infinite; }
  .ripple { fill:none; stroke:#0BD0D9; stroke-width:1.4; opacity:0;
            animation: rip 6.5s linear infinite; }
  .grat { stroke:#9fc6e8; stroke-width:0.5; opacity:0.14; }
  @keyframes pulse { 0%,100% { opacity:var(--o); }
                     50% { opacity:calc(var(--o)*2.2); } }
  @keyframes rip { 0% { r:8; opacity:0.85; } 70% { opacity:0.12; }
                   100% { r:520; opacity:0; } }
  @media (prefers-reduced-motion: reduce) {
    .cell, .ripple { animation:none; } .ripple { display:none; } }
  .card { position:relative; z-index:2; width:min(400px, 92vw);
          padding:2.1rem 2.3rem 1.9rem; border-radius:14px;
          background:rgba(10,28,52,0.55); backdrop-filter:blur(9px);
          -webkit-backdrop-filter:blur(9px);
          border:1px solid rgba(159,198,232,0.25);
          box-shadow:0 18px 50px rgba(0,0,0,0.45); }
  .kicker { font-size:0.72rem; letter-spacing:0.18em; text-transform:uppercase;
            color:#8fd6f2; margin:0 0 0.35rem; }
  h1 { font-size:1.45rem; margin:0 0 0.25rem; color:#fff; }
  .sub { color:#b8d3ea; font-size:0.86rem; margin:0 0 1.3rem; }
  .sub b { color:#dceefb; font-weight:600; }
  input { width:100%; font:inherit; padding:0.55rem 0.7rem; border-radius:8px;
          border:1px solid rgba(159,198,232,0.35); background:rgba(6,20,40,0.6);
          color:#fff; margin-bottom:0.75rem; }
  input::placeholder { color:#7fa3c4; }
  input:focus { outline:2px solid var(--bright); border-color:transparent; }
  button { width:100%; font:inherit; font-weight:600; padding:0.55rem;
           border:0; border-radius:8px; cursor:pointer; color:#06263f;
           background:linear-gradient(90deg,#0BD0D9,#009DD9); }
  button:hover { filter:brightness(1.08); }
  .err { color:#ffb3a7; font-size:0.8rem; min-height:1.2em; margin-top:0.6rem; }
  .foot { margin-top:1.1rem; font-size:0.7rem; color:#7fa3c4; }
</style>
</head>
<body>
<svg id="field" aria-hidden="true" preserveAspectRatio="xMidYMid slice"></svg>
<div class="card">
  <p class="kicker">Exposure analytics</p>
  <h1>Exposure Comparison</h1>
  <p class="sub">Comparing building-exposure models for
     disaster risk management</p>
  <form id="f">
    <input type="password" id="pw" placeholder="Password" autofocus
           autocomplete="current-password">
    <button type="submit">Unlock the explorer</button>
    <div class="err" id="err"></div>
  </form>
  <div class="foot">&copy; Aaron Opdyke</div>
</div>
<script>
/* backdrop: an abstract raster-exposure map — graticule, value cells whose
   intensity clusters like gridded exposure data, hazard ripples sweeping
   out of two epicentres and lighting the cells they pass */
(function () {
  "use strict";
  var svg = document.getElementById("field");
  var W = 1280, H = 800, S = 26;
  svg.setAttribute("viewBox", "0 0 " + W + " " + H);
  var reduce = window.matchMedia &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var eps = [[W * 0.7, H * 0.36], [W * 0.24, H * 0.72]];
  // deterministic pseudo-noise (no Math.random: stable, seedless render)
  function n(x, y) {
    var v = Math.sin(x * 12.9898 + y * 78.233) * 43758.5453;
    return v - Math.floor(v);
  }
  var html = "";
  // graticule
  for (var gx = 0; gx <= W; gx += S * 4)
    html += '<line class="grat" x1="' + gx + '" y1="0" x2="' + gx +
            '" y2="' + H + '"/>';
  for (var gy = 0; gy <= H; gy += S * 4)
    html += '<line class="grat" x1="0" y1="' + gy + '" x2="' + W +
            '" y2="' + gy + '"/>';
  // exposure cells: two clustered "urban centres" + scattered rural noise
  var cols = ["#0BD0D9", "#009DD9", "#0F6FC6", "#7cc0ef"];
  for (var y = 0; y < H; y += S) {
    for (var x = 0; x < W; x += S) {
      var d0 = Math.hypot(x - eps[0][0], y - eps[0][1]);
      var d1 = Math.hypot(x - eps[1][0], y - eps[1][1]);
      var density = Math.max(0, 1 - d0 / 520) + Math.max(0, 1 - d1 / 430);
      var r = n(x, y);
      if (r > density * 0.85 + 0.08) continue;      // empty cell
      var o = Math.min(0.55, 0.05 + density * 0.35 + r * 0.15);
      var c = cols[Math.floor(r * cols.length)];
      var dd = Math.min(d0, d1);
      html += '<rect class="cell" x="' + (x + 2) + '" y="' + (y + 2) +
        '" width="' + (S - 5) + '" height="' + (S - 5) + '" rx="3" fill="' +
        c + '" style="--o:' + o.toFixed(2) +
        (reduce ? '"' : ';animation-delay:' + (dd / 130).toFixed(2) + 's"') +
        "/>";
    }
  }
  if (!reduce) {
    for (var e = 0; e < eps.length; e++)
      for (var k = 0; k < 3; k++)
        html += '<circle class="ripple" cx="' + eps[e][0] + '" cy="' +
          eps[e][1] + '" r="8" style="animation-delay:' +
          (k * 2.2 + e * 1.1).toFixed(1) + 's"/>';
  }
  svg.innerHTML = html;
})();
const SALT = "__SALT__", IV = "__IV__", DATA = "__DATA__", ITER = __ITER__;
const DATA_SHA256 = "__SHA__";
const b64 = s => Uint8Array.from(atob(s), c => c.charCodeAt(0));
async function unlock(pwText) {
  pwText = pwText.trim().replace(/[\\u2010-\\u2015\\u2212]/g, "-")
                 .replace(/\\u00a0/g, " ");
  const pw = new TextEncoder().encode(pwText);
  const km = await crypto.subtle.importKey("raw", pw, "PBKDF2", false, ["deriveKey"]);
  const key = await crypto.subtle.deriveKey(
    { name: "PBKDF2", salt: b64(SALT), iterations: ITER, hash: "SHA-256" },
    km, { name: "AES-GCM", length: 256 }, false, ["decrypt"]);
  const plain = await crypto.subtle.decrypt(
    { name: "AES-GCM", iv: b64(IV) }, key, b64(DATA));
  const html = new TextDecoder().decode(plain);
  try { sessionStorage.setItem("expcmp_pw", pwText); } catch (e) {}
  document.open(); document.write(html); document.close();
}
async function diagnose() {
  if (!window.crypto || !crypto.subtle) {
    return "This browser cannot decrypt the page (no WebCrypto - use a " +
           "current browser over HTTPS; some corporate policies disable it).";
  }
  try {
    const raw = b64(DATA);
    const digest = await crypto.subtle.digest("SHA-256", raw);
    const hex = [...new Uint8Array(digest)]
      .map(b => b.toString(16).padStart(2, "0")).join("");
    if (DATA_SHA256 && hex !== DATA_SHA256) {
      return "The page did not load completely (cached/corrupted copy) - " +
             "hard-refresh (Ctrl+F5) and try again.";
    }
  } catch (e) { /* fall through */ }
  return "Wrong password.";
}
document.getElementById("f").addEventListener("submit", async ev => {
  ev.preventDefault();
  const err = document.getElementById("err");
  err.textContent = "";
  try {
    await unlock(document.getElementById("pw").value);
  } catch (e) {
    err.textContent = await diagnose();
  }
});
(async () => {
  let stored = null;
  try { stored = sessionStorage.getItem("expcmp_pw"); } catch (e) {}
  if (stored) {
    try { await unlock(stored); }
    catch (e) { try { sessionStorage.removeItem("expcmp_pw"); } catch (e2) {} }
  }
})();
</script>
</body>
</html>
"""


_OPEN_FORM = """  <form id="f">
    <button type="submit">Enter the explorer</button>
  </form>"""

_GATED_FORM = """  <form id="f">
    <input type="password" id="pw" placeholder="Password" autofocus
           autocomplete="current-password">
    <button type="submit">Unlock the explorer</button>
    <div class="err" id="err"></div>
  </form>"""

_OPEN_JS = """function enter() {
  try { sessionStorage.setItem("expcmp_entered", "1"); } catch (e) {}
  location.href = "explorer.html";
}
document.getElementById("f").addEventListener("submit", ev => {
  ev.preventDefault();
  enter();
});
/* returning visitors skip the landing entirely */
try {
  if (sessionStorage.getItem("expcmp_entered")) location.replace("explorer.html");
} catch (e) {}
</script>
</body>
</html>
"""


def landing_page(dst):
    """Landing page whose Enter button is a plain navigation to
    explorer.html - no content embedding, no document.write."""
    head = TEMPLATE.split('const SALT =')[0]
    head = head.replace(_GATED_FORM, _OPEN_FORM)
    with open(dst, 'w', encoding='utf-8') as f:
        f.write(head + _OPEN_JS)


def encrypt_page(src, dst, password):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    with open(src, encoding='utf-8') as f:
        html = f.read()
    salt = os.urandom(16)
    iv = os.urandom(12)
    key = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, ITERATIONS)
    ct = AESGCM(key).encrypt(iv, html.encode('utf-8'), None)
    out = (TEMPLATE
           .replace('__SALT__', base64.b64encode(salt).decode())
           .replace('__IV__', base64.b64encode(iv).decode())
           .replace('__DATA__', base64.b64encode(ct).decode())
           .replace('__SHA__', hashlib.sha256(ct).hexdigest())
           .replace('__ITER__', str(ITERATIONS)))
    with open(dst, 'w', encoding='utf-8') as f:
        f.write(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--password', help='password (omit to be prompted)')
    ap.add_argument('--plain', action='store_true',
                    help='copy pages/ to docs/ without a gate (local preview)')
    args = ap.parse_args()

    pages = [f for f in os.listdir(PAGES) if f.endswith('.html')]
    if not pages:
        sys.exit('No HTML files in pages/.')

    if args.plain:
        for f in pages:
            shutil.copy2(os.path.join(PAGES, f), os.path.join(DOCS, f))
        print(f'Copied {len(pages)} plain pages to docs/ (no landing).')
        return

    if args.password:
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: F401
        except ImportError:
            sys.exit('Needs the cryptography package: pip install cryptography')
        for f in pages:
            encrypt_page(os.path.join(PAGES, f), os.path.join(DOCS, f),
                         args.password)
        print(f'Encrypted {len(pages)} pages into docs/ (AES-256-GCM, PBKDF2 '
              f'{ITERATIONS:,} iters).')
        print('NOTE: docs/data/* and docs/assets/* remain publicly fetchable.')
        return

    # default: index.html becomes the landing; the explorer is published as
    # explorer.html and every nav link is repointed at it
    for f in pages:
        with open(os.path.join(PAGES, f), encoding='utf-8') as fh:
            html = fh.read()
        html = html.replace('href="index.html"', 'href="explorer.html"')
        out = 'explorer.html' if f == 'index.html' else f
        with open(os.path.join(DOCS, out), 'w', encoding='utf-8') as fh:
            fh.write(html)
    landing_page(os.path.join(DOCS, 'index.html'))
    print(f'Wrote docs/index.html landing (Enter -> explorer.html) + '
          f'{len(pages)} page(s).')


if __name__ == '__main__':
    main()
