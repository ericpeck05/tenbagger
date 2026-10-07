# Design reference

These three files are the mockup sources for the app. They are a reference for layout and style, not code to reuse.

| File | Screen | Reference width |
| --- | --- | --- |
| `stock-page.dc.html` | Stock page | 1440 px |
| `search.dc.html` | Ticker search, opened with `/` | 720 by 500 px |
| `portfolio.dc.html` | Portfolio | 1440 px |

## How to read them

- They are templates from a design tool, so they will not render correctly if opened directly in a browser. Read them as source.
- All styling is inline in `style="..."` attributes. Colors, sizes, spacing, and fonts in those attributes are the intended values.
- `{{name}}` is a placeholder filled from the `renderVals()` function in the script block at the bottom of each file. `{{accent}}` is the amber accent, `#FFA31A`.
- `<sc-for list="{{rows}}" as="r">` repeats its contents once per row. `<sc-if value="{{flag}}">` shows its contents when the flag is true.
- The sample data in `renderVals()` shows the shape each panel expects, for example the fields of a ratio row or a holdings row.

## What to take and what to leave

- Take: page structure, panel order, column layouts, type sizes, colors, spacing, the numbered title bars, the command line search, and the inverse amber selection style.
- Leave: every company name, ticker, and number. They are made up. LRKS, BRNT, OSLO, and the rest do not exist.
- The candle and line shapes in the charts are hand-drawn sample paths. The real charts use Lightweight Charts with data from the API.
- In the stock page mockup, only the Candles and Line switch is wired up. Range buttons and everything else are static.
