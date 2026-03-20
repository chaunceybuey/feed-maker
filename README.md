# Feed Forge — Simple Edition

Turn any website into an RSS feed using a GitHub repo as free hosting.
No server. No Playwright. No encoding battles.

## How it works

1. You list websites in `feeds.json`
2. A GitHub Action runs every hour, scrapes each site, writes `.xml` files to `feeds/`
3. Your RSS reader subscribes to the raw file URL — e.g.:
   `https://raw.githubusercontent.com/YOUR_USERNAME/YOUR_REPO/main/feeds/the_atlantic.xml`

## Setup

### 1. Create a GitHub repo

Make a new repo (can be private). Upload these files:
- `scrape.py`
- `feeds.json`
- `.github/workflows/scrape.yml`

### 2. Allow the Action to write to the repo

Go to your repo → **Settings → Actions → General → Workflow permissions**
→ select **Read and write permissions** → Save.

### 3. Edit feeds.json

The simplest entry needs just a name and URL — auto-detection handles the rest:

```json
[
  { "name": "The Atlantic", "url": "https://www.theatlantic.com/latest/" },
  { "name": "Kottke",       "url": "https://kottke.org" }
]
```

If auto-detection doesn't work for a site, add a `selector` pointing to
the repeating article container (inspect element, find what wraps each article):

```json
{
  "name": "My Site",
  "url": "https://example.com/blog",
  "selector": "article.post-card"
}
```

You can optionally add `title_sel` and `link_sel` if the auto-extraction
within the container gets the wrong elements:

```json
{
  "name": "Hacker News",
  "url": "https://news.ycombinator.com",
  "selector": "tr.athing",
  "title_sel": "span.titleline > a",
  "link_sel":  "span.titleline > a"
}
```

### 4. Trigger the first run

Go to **Actions → Scrape Feeds → Run workflow** to run it immediately
without waiting for the hourly schedule.

### 5. Get your feed URLs

After the Action runs, a `feeds/` folder will appear in your repo.
Your RSS URL for each feed is:

```
https://raw.githubusercontent.com/YOUR_USERNAME/YOUR_REPO/main/feeds/FILENAME.xml
```

The filename is the lowercased, slugified version of the feed name.
e.g. "The Atlantic" → `the_atlantic.xml`

## Running locally

```bash
pip install requests beautifulsoup4
python scrape.py
```

Output files appear in `feeds/`.

## Troubleshooting

**No items found** — the site probably uses JS rendering. Try adding a `selector`
by inspecting the page source (not DevTools — View Source, which shows the raw HTML
that requests sees). If the articles aren't in View Source at all, the site requires
JavaScript and won't work with this tool.

**Wrong items** — add a `selector` to narrow it down to the right container element.

**Broken links** — the site may use relative URLs. The scraper resolves these
automatically, but if links look wrong, check the `url` field is the correct base URL.
