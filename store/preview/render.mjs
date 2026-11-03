// Local preview renderer for the Keenroll Shopify theme.
// Renders JSON templates + sections with LiquidJS and mock store data into ./dist
// (static HTML) so the theme can be screenshotted without a Shopify store.
// This is a preview approximation; Shopify's real renderer is the source of truth.
import { Liquid, Tag } from 'liquidjs';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const THEME = path.join(here, '..', 'theme');
const POLICIES = path.join(here, '..', 'policies');
const DIST = path.join(here, 'dist');
fs.rmSync(DIST, { recursive: true, force: true });
fs.mkdirSync(path.join(DIST, 'assets'), { recursive: true });

// ---------- engine ----------
const engine = new Liquid({ root: [path.join(THEME, 'snippets')], extname: '.liquid', dynamicPartials: true, jsTruthy: false });

// {% schema %}, {% style %}, {% javascript %}: swallow contents
for (const name of ['schema', 'javascript', 'stylesheet']) {
  engine.registerTag(name, class extends Tag {
    constructor(token, remainTokens, liquid) {
      super(token, remainTokens, liquid);
      while (remainTokens.length) { const t = remainTokens.shift(); if (t.name === 'end' + name) return; }
    }
    *render() { return ''; }
  });
}

// {% form 'type', obj, id: 'x' %} ... {% endform %}
engine.registerTag('form', class extends Tag {
  constructor(token, remainTokens, liquid) {
    super(token, remainTokens, liquid);
    this.args = token.args;
    this.tpls = [];
    const stream = liquid.parser.parseStream(remainTokens)
      .on('tag:endform', () => stream.stop())
      .on('template', (tpl) => this.tpls.push(tpl))
      .on('end', () => { throw new Error('form not closed'); });
    stream.start();
  }
  *render(ctx, emitter) {
    const type = (this.args.match(/'([^']+)'/) || [])[1];
    const id = (this.args.match(/id:\s*([\w'.-]+)/) || [])[1];
    let idVal = id;
    if (id && !id.startsWith("'")) idVal = ctx.getSync(id.split('.'));
    else if (id) idVal = id.replace(/'/g, '');
    const action = { product: '/cart/add', contact: '/contact', storefront_password: '/password' }[type] || '#';
    emitter.write(`<form method="post" action="${action}" id="${idVal || ''}" accept-charset="UTF-8">`);
    ctx.push({ form: { errors: false } });
    yield this.liquid.renderer.renderTemplates(this.tpls, ctx, emitter);
    ctx.pop();
    emitter.write('</form>');
  }
});

// ---------- filters ----------
const money = (c) => '$' + (Number(c || 0) / 100).toFixed(2);
engine.registerFilter('money', money);
engine.registerFilter('money_without_trailing_zeros', (c) => money(c).replace(/\.00$/, ''));
engine.registerFilter('asset_url', (n) => `assets/${n}`);
engine.registerFilter('stylesheet_tag', (u) => `<link rel="stylesheet" href="${u}">`);
engine.registerFilter('script_tag', (u) => `<script src="${u}"></script>`);
engine.registerFilter('image_url', (img) => (img && img.src) || '');
engine.registerFilter('image_tag', (u) => `<img src="${u}" alt="">`);
engine.registerFilter('default_errors', () => 'Please check the form.');

// ---------- section rendering ----------
function readSection(type) {
  const src = fs.readFileSync(path.join(THEME, 'sections', `${type}.liquid`), 'utf8');
  const m = src.match(/{%\s*schema\s*%}([\s\S]*?){%\s*endschema\s*%}/);
  const schema = m ? JSON.parse(m[1]) : { settings: [] };
  return { src, schema };
}
const defaults = (arr = []) => Object.fromEntries(arr.filter((s) => 'default' in s).map((s) => [s.id, s.default]));

async function renderSection(id, type, data = {}, globals) {
  const { src, schema } = readSection(type);
  const settings = { ...defaults(schema.settings), ...(data.settings || {}) };
  const blocks = (data.block_order || []).map((bid) => {
    const b = data.blocks[bid];
    const bs = (schema.blocks || []).find((x) => x.type === b.type) || {};
    return { id: bid, type: b.type, settings: { ...defaults(bs.settings), ...(b.settings || {}) }, shopify_attributes: '' };
  });
  const section = { id, settings, blocks };
  return engine.parseAndRender(src, { ...globals, section });
}

// {% section 'name' %} used in layout
engine.registerTag('section', class extends Tag {
  constructor(token, remainTokens, liquid) { super(token, remainTokens, liquid); this.name = token.args.replace(/['"\s]/g, ''); }
  *render(ctx, emitter) {
    const html = yield renderSection(this.name, this.name, {}, ctx.getAll());
    emitter.write(html);
  }
});

// ---------- mock store data ----------
const read = (p) => fs.readFileSync(p, 'utf8');
const settingsData = JSON.parse(read(path.join(THEME, 'config', 'settings_data.json'))).presets.Default;
const product = {
  title: 'Keenroll Rolling Knife Sharpener Kit',
  handle: 'keenroll-rolling-knife-sharpener',
  url: '/products/keenroll-rolling-knife-sharpener',
  available: true,
  media: [], featured_media: null,
  description: '<p><strong>In the box:</strong> solid-wood roller with a diamond disc (#400) and a ceramic honing disc (#1000), a magnetic angle block (15° / 20°), a cleaning cloth, and a quick-start card.</p><p><strong>Size:</strong> roller ≈ 6 × 6 × 9 cm. Block ≈ 9 × 5 × 4 cm. <strong>Weight:</strong> ≈ 450 g.</p><p><strong>Care:</strong> wipe the discs with a dry cloth after use. Don\'t submerge the wood in water.</p><p><em>Specs to be confirmed against your supplier sample.</em></p>',
  variants: [
    { id: 1001, title: '1 Kit', option1: '1 Kit', price: 5900, available: true },
    { id: 1002, title: '2 Kits', option1: '2 Kits', price: 9800, available: true },
    { id: 1003, title: '3 Kits', option1: '3 Kits', price: 12900, available: true },
  ],
};
product.selected_or_first_available_variant = product.variants[0];
product.price = 5900;

const emptyCart = { item_count: 0, items: [], total_price: 0 };
const fullCart = {
  item_count: 1, total_price: 9800, note: '',
  items: [{ title: product.title, url: product.url, url_to_remove: '#', quantity: 1, final_line_price: 9800, image: null,
    product: { title: product.title, has_only_default_variant: false }, variant: { title: '2 Kits' } }],
};
const baseGlobals = {
  shop: { name: 'Keenroll', password_message: 'Sharp knives, zero skill. Launching soon.' },
  settings: settingsData,
  routes: { root_url: '/', cart_url: '/cart', search_url: '/search' },
  linklists: {}, request: { locale: { iso_code: 'en' } }, canonical_url: '/', current_page: 1,
  content_for_header: '',
};

// ---------- pages to render ----------
const policyTitle = { 'privacy-policy': 'Privacy Policy', 'refund-policy': 'Refund Policy', 'shipping-policy': 'Shipping Policy', 'terms-of-service': 'Terms of Service' };
const pages = [
  { out: 'index.html', tpl: 'index', title: 'Keenroll · Rolling Knife Sharpener', cart: emptyCart },
  { out: 'product.html', tpl: 'product', title: product.title, cart: emptyCart, extra: { product } },
  { out: 'about.html', tpl: 'page.about', title: 'Our story', cart: emptyCart, extra: { page: { title: 'Our story' } } },
  { out: 'contact.html', tpl: 'page.contact', title: 'Contact', cart: emptyCart, extra: { page: { title: 'Contact' } } },
  { out: 'track-order.html', tpl: 'page.track-order', title: 'Track your order', cart: emptyCart, extra: { page: { title: 'Track order' } } },
  { out: 'cart.html', tpl: 'cart', title: 'Your cart', cart: fullCart },
  { out: '404.html', tpl: '404', title: 'Not found', cart: emptyCart, name: '404' },
  ...Object.keys(policyTitle).map((p) => ({
    out: `${p}.html`, tpl: 'page', title: policyTitle[p], cart: emptyCart,
    extra: { page: { title: policyTitle[p], content: read(path.join(POLICIES, `${p}.html`)) } },
  })),
];

const linkMap = {
  '/products/keenroll-rolling-knife-sharpener': 'product.html', '/': 'index.html', '/cart': 'cart.html',
  '/pages/about': 'about.html', '/pages/contact': 'contact.html', '/pages/track-order': 'track-order.html',
  '/policies/privacy-policy': 'privacy-policy.html', '/policies/refund-policy': 'refund-policy.html',
  '/policies/shipping-policy': 'shipping-policy.html', '/policies/terms-of-service': 'terms-of-service.html',
};

// local fonts for preview (Google Fonts is unreachable from the sandbox)
const fontCss = `<style>
@font-face{font-family:Fraunces;font-weight:700;src:url(assets/fraunces-700.woff2) format('woff2')}
@font-face{font-family:Fraunces;font-weight:600;src:url(assets/fraunces-600.woff2) format('woff2')}
@font-face{font-family:Inter;font-weight:400;src:url(assets/inter-400.woff2) format('woff2')}
@font-face{font-family:Inter;font-weight:500;src:url(assets/inter-500.woff2) format('woff2')}
@font-face{font-family:Inter;font-weight:600;src:url(assets/inter-600.woff2) format('woff2')}
@font-face{font-family:Inter;font-weight:700;src:url(assets/inter-700.woff2) format('woff2')}
@font-face{font-family:Inter;font-weight:800;src:url(assets/inter-800.woff2) format('woff2')}
</style>`;

const layoutSrc = read(path.join(THEME, 'layout', 'theme.liquid'));
for (const p of pages) {
  const tplJson = JSON.parse(read(path.join(THEME, 'templates', `${p.tpl}.json`)));
  const templateName = p.name || p.tpl.split('.')[0];
  const globals = { ...baseGlobals, cart: p.cart, page_title: p.title, template: { name: templateName }, ...(p.extra || {}) };
  let body = '';
  for (const sid of tplJson.order) {
    const s = tplJson.sections[sid];
    body += await renderSection(sid, s.type, s, globals);
  }
  let html = await engine.parseAndRender(layoutSrc, { ...globals, content_for_layout: body });
  html = html.replace(/<link href="https:\/\/fonts\.googleapis[^>]+>/, fontCss);
  html = html.replace(/href="([^"#]+)(#[^"]*)?"/g, (m, url, hash = '') => (linkMap[url] ? `href="${linkMap[url]}${hash}"` : m));
  fs.writeFileSync(path.join(DIST, p.out), html);
}

// assets
for (const f of fs.readdirSync(path.join(THEME, 'assets'))) fs.copyFileSync(path.join(THEME, 'assets', f), path.join(DIST, 'assets', f));
const fsrc = (pkg, w) => path.join(here, 'node_modules', '@fontsource', pkg, 'files', `${pkg}-latin-${w}-normal.woff2`);
for (const w of [600, 700]) fs.copyFileSync(fsrc('fraunces', w), path.join(DIST, 'assets', `fraunces-${w}.woff2`));
for (const w of [400, 500, 600, 700, 800]) fs.copyFileSync(fsrc('inter', w), path.join(DIST, 'assets', `inter-${w}.woff2`));
console.log('Rendered', pages.length, 'pages to', DIST);
