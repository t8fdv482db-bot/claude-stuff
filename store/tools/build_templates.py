"""Generates theme/templates/*.json, config and locales for the Keenroll theme.
Edit copy here (or in the Shopify theme editor after upload)."""
import json, os
ROOT = os.path.join(os.path.dirname(__file__), '..', 'theme')
PRODUCT_URL = '/products/keenroll-rolling-knife-sharpener'

def blocks(prefix, items):
    b = {f'{prefix}_{i}': it for i, it in enumerate(items, 1)}
    return b, list(b.keys())

def sec(type_, settings=None, blocks_items=None, prefix='b'):
    s = {'type': type_, 'settings': settings or {}}
    if blocks_items:
        s['blocks'], s['block_order'] = blocks(prefix, blocks_items)
    return s

def tpl(sections, layout=None):
    d = {'sections': sections, 'order': list(sections.keys())}
    if layout: d['layout'] = layout
    return d

def benefit(icon, title, text): return {'type': 'benefit', 'settings': {'icon': icon, 'title': title, 'text': text}}
def step(title, text): return {'type': 'step', 'settings': {'title': title, 'text': text}}
def row(f, us, a, b, c): return {'type': 'row', 'settings': {'feature': f, 'us': us, 'a': a, 'b': b, 'c': c}}
def q(question, answer): return {'type': 'question', 'settings': {'question': question, 'answer': answer}}
def bullet(t): return {'type': 'bullet', 'settings': {'text': t}}

BENEFITS = [
    benefit('angle', 'Locked-in angle', 'The magnetic block holds your blade at exactly 15° or 20°. No wobble, no guesswork, no "am I doing this right?"'),
    benefit('clock', 'About a minute', '20 rolls a side on diamond, 10 on ceramic. Done before the pasta water boils.'),
    benefit('diamond', 'Diamond + ceramic', 'The diamond disc sets the edge. The ceramic disc polishes it smooth.'),
    benefit('gift', 'Made for gifting', 'Solid wood, a satisfying magnet, and a gift-ready box. It looks like more than it costs.'),
]
STEPS = [
    step('Stick', 'Set your knife on the magnetic block. Use the 15° side for thin Japanese-style knives and 20° for Western knives.'),
    step('Roll', 'Roll the diamond disc along the edge about 20 times. Flip the knife over and repeat.'),
    step('Polish & slice', 'Switch to the ceramic disc for about 10 rolls per side. Then slice a tomato and enjoy it.'),
]
ROWS = [
    row('Easy for beginners', '✓', '✓', '✗ Steep learning curve', '✓'),
    row('Choose your angle (15° / 20°)', '✓', '✗ Usually one fixed slot', '✓ If you\'re skilled', 'Some models'),
    row('Even, controlled sharpening', '✓', '✗ Can chip or tear edges', '✓', 'Aggressive'),
    row('No water, power, or mess', '✓', '✓', '✗ Soaking & slurry', '✗ Needs an outlet'),
    row('Typical price', '$59 kit', '$10–25', '$30–80 + practice', '$50–200'),
    row('Nice enough to gift', '✓', '✗', 'Meh', '✗'),
]
FAQ_FULL = [
    q('Will it work on my knives?', '<p>It works on most <strong>straight-edged</strong> (non-serrated) steel kitchen, chef, santoku, paring, and pocket knives. It\'s <strong>not</strong> for serrated bread knives, scissors, ceramic knives, or single-bevel Japanese knives (yanagiba, deba).</p>'),
    q('15° or 20°: which side do I use?', '<p><strong>15°</strong> for thin Japanese-style knives (santoku, gyuto). <strong>20°</strong> for most Western/German-style chef knives. Not sure? Start with 20°.</p>'),
    q('Will it damage my good knives?', '<p>A fixed angle means you sharpen the edge you already have instead of grinding a new one. Start with fewer rolls (10–20 per side) and check the edge. You can always do more. Pull-through sharpeners work differently: they scrape the edge through a fixed V-slot.</p>'),
    q('How often should I use it?', '<p>Use the ceramic side for a quick touch-up every week or two. Use the diamond side when the knife starts squashing tomatoes, typically every 1–3 months for home cooks.</p>'),
    q('How long does shipping take?', '<p>Orders are processed in 1–3 business days. US delivery then takes about 7–12 business days, so plan on <strong>8–15 business days total</strong>. You\'ll get a tracking number by email. Full details are on our <a href="/policies/shipping-policy">shipping policy</a>.</p>'),
    q('Is it a good gift? Can I hide the price?', '<p>Yes. It arrives in a gift-ready box, and we never put prices in the package. Add a gift note at checkout.</p>'),
    q('What if it doesn\'t work for me?', '<p>You have 60 days from delivery. If it doesn\'t sharpen your knives, email us for a full refund. See our <a href="/policies/refund-policy">refund policy</a>.</p>'),
    q('Is it safe to use?', '<p>The magnet holds the blade steady, so your hands stay on the roller, away from the edge. Always keep fingers clear of the blade, cut away from your body, and store it out of reach of children.</p>'),
    q('Where is it made?', '<p>Keenroll is designed for home cooks and made by our manufacturing partner in China. We check samples from every supplier batch before selling them.</p>'),
]
FAQ_SHORT = FAQ_FULL[:3] + FAQ_FULL[4:5] + FAQ_FULL[6:7]

benefits_sec = lambda **kw: sec('benefits', {'eyebrow': 'Why it works', 'heading': 'Sharp knives without the learning curve', 'columns': '4', **kw}, BENEFITS)
how_sec = sec('how-it-works', {}, STEPS)
compare_sec = sec('comparison', {}, ROWS)

templates = {
  'index': tpl({
    'hero': sec('hero'),
    'benefits': benefits_sec(white=True),
    'how': how_sec,
    'compare': compare_sec,
    'reviews': sec('reviews'),
    'guarantee': sec('guarantee'),
    'faq': sec('faq', {}, FAQ_SHORT),
    'cta': sec('cta-banner'),
  }),
  'product': tpl({
    'main': sec('main-product', {}, [
        bullet('Locked 15° & 20° angles. The magnet does the hard part.'),
        bullet('Diamond disc sharpens, ceramic disc polishes.'),
        bullet('Works on most straight-edge kitchen & pocket knives.'),
        bullet('No water, no oil, no electricity, no skill.'),
        bullet('Solid wood roller in a gift-ready box.'),
    ]),
    'benefits': benefits_sec(white=True, heading='Why home cooks actually use it'),
    'how': how_sec,
    'compare': compare_sec,
    'reviews': sec('reviews'),
    'guarantee': sec('guarantee'),
    'faq': sec('faq', {}, FAQ_FULL),
    'cta': sec('cta-banner', {'button_link': '#MainContent', 'button_label': 'Choose your kit'}),
  }),
  'page': tpl({'main': sec('main-page')}),
  'page.about': tpl({
    'story': sec('rich-text', {'eyebrow': 'Our story', 'heading': 'Sharp knives make cooking fun again.', 'is_h1': True, 'text':
      '<p>Almost every kitchen has a good knife that has gone dull. It squashes tomatoes, slides off onion skins, and turns dinner into a chore. Most of us mean to get it sharpened "someday."</p>'
      '<p>Whetstones take practice. Pull-through gadgets can chew up an edge. Mail-in services take weeks. So we went looking for the easiest way to get a properly sharp edge at home, and landed on the rolling sharpener: a magnet holds the angle, and you just roll.</p>'
      '<p><strong>Keenroll</strong> is a small, independent online shop built around that one tool. We keep it simple: one great product, honest shipping times, real reviews only, and a 60-day guarantee.</p>'}),
    'values': sec('benefits', {'eyebrow': 'What we stand for', 'heading': 'The Keenroll promise', 'columns': '3', 'white': True}, [
      benefit('check', 'Honest, always', 'No fake countdowns, no fake "only 2 left," no fake reviews. If we say it, it\'s true.'),
      benefit('shield', '60 days to decide', 'Sharp, or it\'s free. Simple as that.'),
      benefit('truck', 'Real delivery times', 'We tell you how long shipping actually takes, before you buy.'),
    ]),
    'cta': sec('cta-banner'),
  }),
  'page.contact': tpl({'main': sec('contact-form')}),
  'page.track-order': tpl({'main': sec('track-order')}),
  'cart': tpl({'main': sec('main-cart')}),
}
for name in ['404', 'search', 'collection', 'list-collections', 'blog', 'article']:
    templates[name] = tpl({'main': sec('main-generic')})
templates['password'] = tpl({'main': sec('main-generic')}, layout='password')

os.makedirs(os.path.join(ROOT, 'templates'), exist_ok=True)
for name, data in templates.items():
    with open(os.path.join(ROOT, 'templates', f'{name}.json'), 'w') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

settings_schema = [
  {'name': 'theme_info', 'theme_name': 'Keenroll', 'theme_version': '1.0.0', 'theme_author': 'Keenroll',
   'theme_documentation_url': 'https://shopify.dev/docs/themes', 'theme_support_url': 'https://help.shopify.com'},
  {'name': 'Colors', 'settings': [
    {'type': 'color', 'id': 'color_ink', 'label': 'Ink (text)', 'default': '#1C1D1F'},
    {'type': 'color', 'id': 'color_wood', 'label': 'Walnut', 'default': '#8A5A3B'},
    {'type': 'color', 'id': 'color_cream', 'label': 'Cream (background)', 'default': '#F6F1E9'},
    {'type': 'color', 'id': 'color_steel', 'label': 'Steel', 'default': '#9AA3AB'},
    {'type': 'color', 'id': 'color_accent', 'label': 'Edge orange (buttons)', 'default': '#E8692C'},
  ]},
  {'name': 'Shipping estimate', 'settings': [
    {'type': 'paragraph', 'content': 'Used for the delivery-date estimate on the product page. Set from your supplier\'s REAL processing + transit time (business days).'},
    {'type': 'range', 'id': 'delivery_min_days', 'label': 'Min business days', 'min': 1, 'max': 30, 'step': 1, 'default': 8},
    {'type': 'range', 'id': 'delivery_max_days', 'label': 'Max business days', 'min': 1, 'max': 30, 'step': 1, 'default': 15},
  ]},
  {'name': 'Favicon', 'settings': [{'type': 'image_picker', 'id': 'favicon', 'label': 'Favicon (32×32 PNG)'}]},
]
with open(os.path.join(ROOT, 'config', 'settings_schema.json'), 'w') as f:
    json.dump(settings_schema, f, indent=2, ensure_ascii=False)
with open(os.path.join(ROOT, 'config', 'settings_data.json'), 'w') as f:
    json.dump({'current': 'Default', 'presets': {'Default': {
        'color_ink': '#1C1D1F', 'color_wood': '#8A5A3B', 'color_cream': '#F6F1E9', 'color_steel': '#9AA3AB',
        'color_accent': '#E8692C', 'delivery_min_days': 8, 'delivery_max_days': 15}}}, f, indent=2)
with open(os.path.join(ROOT, 'locales', 'en.default.json'), 'w') as f:
    json.dump({'general': {'skip': 'Skip to content'}}, f, indent=2)
print('ok', len(templates), 'templates')
