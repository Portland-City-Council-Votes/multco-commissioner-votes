# Multnomah County Commission Votes

A searchable record of how Multnomah County's commissioners have voted on major items since January 2017: the current Board (Chair Jessica Vega Pederson and Commissioners Meghan Moyer, Shannon Singleton, Julia Brim-Edwards and Vince Jones-Dixon) and former Commissioner Sharon Meieran, alongside everyone else who sat on the Board in that time. Filter by theme, year, commissioner, how they voted, or split votes only. A seat someone didn't hold at the time of a vote shows as "not in office".

It's a static site with no build step: `index.html` loads `data/votes.csv` and does all filtering in the browser.

## Preview locally

```sh
python3 -m http.server
```

Then open http://localhost:8000.

## Publish with GitHub Pages

In the repository's **Settings → Pages**, set the source to **Deploy from a branch**, pick the branch and `/ (root)`, and save.

## Data

- `data/votes.csv`: one row per major agenda item, with each commissioner's vote.
- `data/motions.csv`: amendment and other roll calls under those items.
- `data/meetings.csv`: which meetings have been processed.
- `data/picks/`: the editorial record behind the CSVs (which items were logged, synopses, themes, and any corrections after reading the minutes).

The votes come from the official Board minutes and agendas in the Board Clerk's archive at [multnomah.granicus.com](https://multnomah.granicus.com/ViewPublisher.php?view_id=3). Synopses, themes and the choice of which items count as "major" are editorial calls, not official County categories. See [CLAUDE.md](CLAUDE.md) for the schema, how the minutes record votes, and the rules for what gets included.

Check the data before committing:

```sh
python3 scripts/validate_data.py
```
