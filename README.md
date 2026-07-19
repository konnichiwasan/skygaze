# skygaze

> A "look straight up" planetarium that draws the real sky **and live aircraft overhead** in your browser — zero dependencies, zero running cost.

Lie back and look up. skygaze renders a realistic sky for your location — a
time-of-day gradient, the Sun, the Moon (with its current phase), and named
stars + constellations — then overlays **live aircraft** at their true
azimuth and elevation, gliding smoothly between data pulls. Planes closing in
on you are highlighted and can chime; click any one and a free AI explains
what it is and what it's doing.

Inspired by the [Toasty app Instagram post](https://www.instagram.com/toastytheapp/p/DZLGcnllds4/?img_index=7).

## Why

- **The real sky, not a cartoon.** Sun/Moon/phase, rise-set times, and stars
  that fade in as daylight fades — matched to your coordinates and clock.
- **Planes where they actually are.** Live positions from OpenSky, drawn at
  true azimuth/elevation and interpolated so they glide instead of jumping.
- **Immersive by default.** All chrome hides itself; move the mouse (or press
  `H`) to reveal it for a couple of seconds. It's meant to fool your eye.
- **Zero running cost.** Sky math is local, aircraft are free (OpenSky), the
  AI uses free models only, and the optional route lookup is budget-guarded so
  it can never leave the free tier.

## Run

```bash
python3 skygaze.py
# open http://127.0.0.1:8753/
```

Pure Python standard library + a browser. **No pip install.** Aircraft come
from the free OpenSky Network API; map tiles (Location picker only) from
OpenStreetMap.

## Controls

Chrome is hidden by default — move the mouse or press `H`.

| Key | Action |
|---|---|
| `H` | show/hide controls |
| `C` | constellation lines |
| `L` | star labels |
| `S` | sound (overhead chime + approach tone) |
| `F` | fullscreen |
| `A` | Ask-AI panel |
| click a plane | AI explains that flight |

## Features

- **Sky:** gradient by time of day, Sun with glow, Moon with phase, planets,
  and named stars + constellations (labels on by default).
- **Live flights:** true az/el placement, smooth interpolation, sky and radar
  views, airline from callsign, altitude-coloured glyphs.
- **Approaching alerts:** flights getting closer get a pulsing ring, a
  closing-speed label, top billing in the status panel, and a distinct rising
  two-note tone (separate from the soft overhead chime).
- **Click-to-explain:** tap any plane and a free model explains it from its
  live data — airline, altitude band, heading, and whether it's coming closer.
- **Tonight's Wonder:** an auto-rotating fun-fact card driven by the live sky
  and any approaching flight.
- **Immersive mode:** everything fades away until you ask for it.

## Configuration

Optional keys live in `config.json` (gitignored — copy `config.example.json`):

```json
{
  "openrouter_key": "",
  "aviationstack_key": ""
}
```

- **`openrouter_key`** — enables the Ask-AI panel, click-to-explain, and the
  fun-fact card. Uses **free models only** (`openai/gpt-oss-20b:free` plus
  free fallbacks). The key is read server-side and **never sent to the
  browser**.
- **`aviationstack_key`** — enables real **from → to** city pairs. Kept at
  **$0**: every callsign is cached to disk (looked up at most once) and a
  persistent monthly counter hard-stops at 95 of the 100 free calls, so the
  paid tier is never touched. Without it, flights show airline + live compass
  heading.

Tune `OBSERVER_DEFAULT`, `RADIUS_KM`, `REFRESH_S`, and `PORT` near the top of
`skygaze.py`. The default location is Marina Beach, Chennai; change it in-app
via the map picker (`H` → Location → drag → Use this location).

## Privacy

- No IP-based geolocation — the viewer's IP is never sent to any third party.
- The `/location` endpoint only ever returns the fixed default; it queries no
  external geo service.
- API keys stay in the gitignored `config.json` and never reach the frontend.

## Endpoints

`/` (page) · `/scene` (astronomy JSON) · `/planes` (aircraft JSON) ·
`/location` (fixed default) · `/ai/ask` (server-side AI proxy).

## License

MIT — see [LICENSE](LICENSE).
