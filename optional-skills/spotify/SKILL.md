# Spotify

> Jerome's Spotify playback control — search, play, pause, skip, now playing

**Version:** 0.1.0
**Author:** claude
**Agents:** jerome

## Usage
Wraps the existing `SpotifyPlugin`. Requires Spotify OAuth tokens in `.env`
(`SPOTIFY_ACCESS_TOKEN` / `SPOTIFY_REFRESH_TOKEN`). Degrades gracefully with a
clear message when no token or no active device is present.

## Commands
- `play_focus <input>` — search the library and play the best match for `<input>`
- `pause <input>` — pause current playback
- `skip <input>` — skip to the next track
- `now_playing <input>` — show the currently playing track

## Example Output
```
Pun „Weightless” — Marconi Union. 🎧
Acum: „Weightless” — Marconi Union.
```
