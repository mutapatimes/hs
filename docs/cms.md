# Mini-CMS: editing site copy without code

Phase 1 lets an operator edit marketing **copy** (text) from a browser, no deploy required.

## How it works

Editable text is wrapped inline in a page's HTML with comment delimiters:

```html
<h1 class="display"><!--cms:home.hero.title-->Your <em>headline</em><!--/cms--></h1>
```

- The text between the markers is the **default** — it ships in git and renders if nothing is set.
- At `/admin`, an operator can override any block. The override is stored in the `content` table
  (in the database, so it survives Render redeploys) and injected at serve time by
  `apply_overrides()` — which both the homepage (`/`) and `_serve_page()` run through.
- The comment markers are invisible in the browser and are **kept** after substitution, so a block
  stays editable.

Nothing here is customer data — it is website copy.

## Using it

1. Set `HALIA_ADMIN_KEY` in the environment (unset → `/admin` is disabled).
2. Go to `/admin`, enter the key. You get a signed, 12-hour cookie.
3. Edit any field and **Save changes** — it's live immediately (a 20s in-process cache aside).
   HTML such as `<em>` is allowed. Blanking a field, or setting it back to the original text,
   **reverts** it (the override is deleted).

## Adding more editable blocks

Wrap any text in a page under `web/site/` with a unique key:

```html
<p class="lede"><!--cms:pricing.hero.sub-->Simple, honest pricing.<!--/cms--></p>
```

Keys are free-form (`page.section.field` by convention). The block appears in `/admin`
automatically on next load — no other change needed. Currently marked:

- `home.hero.eyebrow`, `home.hero.title`, `home.hero.sub`
- `solutions.hero.title`
- `clienteling.hero.title`

## Notes / limits (Phase 1)

- Copy only. Images (media manager) and structured content (testimonials/case studies) are the
  next phases — see the CMS scope discussion.
- A block's text can be duplicated elsewhere unmarked (e.g. the homepage `<meta description>`
  repeats the hero sub); those copies don't auto-update. Mark them too if you want them editable.
- Auth is a single shared admin key (operator tool), not per-user accounts.

Code: `halia/api/content.py` (inject + scan + `/admin`), `store.get/set/delete_content`,
`config.ADMIN_KEY`.
