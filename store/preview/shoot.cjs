const { chromium } = require('playwright');
const path = require('path'); const fs = require('fs');
const dist = path.join(__dirname, 'dist'); const out = path.join(__dirname, '..', 'screenshots');
fs.mkdirSync(out, { recursive: true });
const pages = fs.readdirSync(dist).filter(f => f.endsWith('.html'));
(async () => {
  const browser = await chromium.launch();
  for (const [label, vp] of [['mobile', { width: 390, height: 844 }], ['desktop', { width: 1440, height: 900 }]]) {
    const ctx = await browser.newContext({ viewport: vp, deviceScaleFactor: label === 'mobile' ? 2 : 1, isMobile: label === 'mobile', hasTouch: label === 'mobile' });
    const page = await ctx.newPage();
    const errs = [];
    page.on('pageerror', e => errs.push(e.message));
    for (const f of pages) {
      await page.goto('file://' + path.join(dist, f));
      await page.waitForTimeout(250);
      const name = f.replace('.html', '');
      await page.screenshot({ path: path.join(out, `${name}-${label}.png`), fullPage: true });
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
      if (overflow) console.log('HORIZONTAL OVERFLOW', name, label);
    }
    if (label === 'mobile') { // sticky ATC check
      await page.goto('file://' + path.join(dist, 'product.html'));
      await page.evaluate(() => window.scrollTo(0, 1600)); await page.waitForTimeout(500);
      await page.screenshot({ path: path.join(out, `product-sticky-atc-mobile.png`) });
    }
    if (errs.length) console.log('JS errors', label, errs);
    await ctx.close();
  }
  await browser.close();
  console.log('done', pages.length * 2 + 1, 'screenshots');
})();
