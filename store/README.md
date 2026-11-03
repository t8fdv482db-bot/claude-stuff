# Keenroll Store: Shopify Theme

A custom, mobile-first **Shopify Online Store 2.0 theme** built for one hero product: the Keenroll rolling knife sharpener kit.

## Why Shopify (and a custom theme)

- **Shopify** handles checkout, payments, taxes, fraud, Shop Pay (high conversion), and has the best dropshipping integrations (CJ Dropshipping and DSers apps), TikTok and Meta sales channels with pixels built in, and review apps. Building our own checkout would be slower, riskier, and convert worse.
- **Custom theme instead of a stock theme plus page builder:** a single-product store needs one strong product page, not a catalog. This theme is small (no frameworks, about 3 KB of JS) so it loads fast on mobile, which is where TikTok traffic lands. Every section is still editable in the Shopify theme editor.
- **Passes Shopify Theme Check** with 0 errors. The 4 warnings are about loading Google Fonts from Google's servers, which is intentional. Swap to the Shopify font library later if you want.

## What's included

```
store/
├── theme/                  ← upload this folder to Shopify
│   ├── layout/             theme.liquid, password.liquid
│   ├── sections/           hero, benefits, how-it-works, comparison, faq, guarantee,
│   │                       reviews (app-block slot), cta-banner, rich-text, main-product
│   │                       (bundle selector + sticky ATC), contact-form, track-order,
│   │                       main-cart, main-page, main-generic, header, footer, announcement-bar
│   ├── templates/          index, product, page, page.about, page.contact, page.track-order,
│   │                       cart, 404, search, collection, list-collections, blog, article, password
│   ├── snippets/icon.liquid
│   ├── assets/             theme.css, theme.js, logos, placeholder illustration
│   ├── config/             settings_schema.json, settings_data.json
│   └── locales/
├── policies/               Privacy, Terms, Refund, Shipping (HTML to paste into Shopify)
├── preview/                local preview renderer (LiquidJS + mock data) + screenshot script
├── screenshots/            every page, mobile (390px) + desktop (1440px)
└── tools/build_templates.py  regenerates templates/config. All page copy lives here
```

### Product page features

- Hook headline, benefit bullets, how-it-works, comparison vs. other sharpener types, FAQ, 60-day guarantee
- **Bundle selector** built from product variants (1 / 2 / 3 Kits). The "You save $X" amount is **calculated** (single price × qty − bundle price), never an inflated compare-at price
- **Sticky add-to-cart** that appears after the main button scrolls off-screen (mobile bar, desktop pill)
- **Truthful urgency only:**
  - A delivery-date estimate calculated from **your** settings (Theme settings → Shipping estimate, default 8–15 business days)
  - A holiday cutoff notice you control (default "order by Dec 1"). **Update it to match your supplier's real times and turn it off once the date passes**
  - No countdown timers, no stock counters
- **Reviews:** a placeholder that says honestly that you're new. Install **Judge.me** (free) and add its app block in the Reviews section and under the product title. **Never import or write fake reviews.**
- Gift note in cart, plus a safety line in the footer

## Deploy (about 20 minutes)

### 1. Install Shopify CLI
```bash
# needs Node 18+
npm install -g @shopify/cli@latest
```

### 2. Create the product in Shopify admin FIRST
**Products → Add product**
- **Title:** `Keenroll Rolling Knife Sharpener Kit`
- **URL handle** (under "Search engine listing"): `keenroll-rolling-knife-sharpener`. The theme links here.
- **Description:** copy from `preview/render.mjs` (`product.description`), then **edit the specs to match your actual sample**
- **Variants:** option name `Bundle`, values **exactly** `1 Kit`, `2 Kits`, `3 Kits` (the number at the start drives the savings math)
  - Prices: `59.00`, `98.00`, `129.00`
  - Leave **Compare-at price empty**
  - Uncheck "Track quantity" (dropshipping), or let your supplier app sync stock
  - Weight: about 0.5 kg / 1.0 kg / 1.5 kg
- **Media:** your own photos and video (see `/content/filming-guide.md`). Until then, the theme shows an illustration with an honest "illustration shown" note.

### 3. Upload the theme
```bash
cd store/theme
shopify theme push --unpublished --store your-store.myshopify.com
# opens a login in the browser; then gives you a preview link
```
Or zip the **contents** of `store/theme/` and use **Online Store → Themes → Add theme → Upload zip file**.

### 4. Create pages (Online Store → Pages)
| Page title | Handle | Template |
|---|---|---|
| Our story | `about` | `page.about` |
| Contact | `contact` | `page.contact` |
| Track your order | `track-order` | `page.track-order` |

(The page body can be empty. The copy lives in the sections. Edit it in the theme editor.)

### 5. Policies (Settings → Policies)
Paste each file from `store/policies/` into the matching box and **replace every `[PLACEHOLDER]`** (business name, email, address, state, date). The footer links to `/policies/...` automatically.
> These are solid starting templates, not legal advice. Have a lawyer review them once you're doing real volume.

### 6. Navigation (optional)
The header falls back to Shop / Our story / Track order / Contact. To customize, create a menu with handle `main-menu`.

### 7. Theme editor check
**Online Store → Themes → Customize:**
- Footer: set your support email and social links
- Product page: check the holiday cutoff text and highlighted bundle tag
- Theme settings → Shipping estimate: set min/max business days from your supplier's real times
- Upload your hero photo in the Hero section

### 8. Publish
Preview on your phone first, then click **Publish**.

## Local preview (optional, already done for you)

```bash
cd store/preview
npm install
node render.mjs          # renders theme + mock data → dist/*.html
node shoot.cjs           # screenshots → ../screenshots (needs Playwright)
```
The preview is an approximation (LiquidJS with mock data). Shopify's own renderer is the source of truth. For a live dev server against your store: `cd store/theme && shopify theme dev --store your-store.myshopify.com`.

## Things that need YOUR real input before launch

- [ ] Real product photos and video (no unapproved supplier images)
- [ ] Specs in the product description, matched to your sample (size, weight, grits)
- [ ] Policy placeholders filled in
- [ ] Support email set up (e.g. Google Workspace or Zoho on your domain)
- [ ] Holiday cutoff date matched to your actual supplier's shipping times
- [ ] About page: add a sentence about who you are (real people convert better). Keep it true.
