# H516 video: next design checkpoint

Generated 2026-09-27; base/head bd2bb70ead1b493043a335e77713fc42c47d4013
plus preserved local work. Goal: real governed video generation/rendering.
No implementation GO or completion claim in this checkpoint. Next action: settle
provider, validated artifact/decoder, durable job recovery and shared-registry
contracts before assigning source ownership.

The frozen H516 row requires prompt/still-image generation, local and cloud
backends through a provider seam, and a usable render stage. H517 currently
registers only a finite local image protocol. Existing Nerva video planning remains
honestly unrendered; a new HTTP endpoint alone would not close H516.

The pinned Hermes reference at revision
`59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e`,
`plugins/video_gen/xai/__init__.py:208–315`, supplies a concrete offline-testable
cloud protocol: POST `/videos/generations` with model/prompt/duration/aspect ratio/
resolution, then GET `/videos/{request_id}` to a terminal status. Success gives
`video.url` or `video.file_output.public_url`. Nerva should refuse invalid options
instead of copying silent clamping. Implementing tests authorizes no paid calls.

A candidate first slice is one default-off text-to-video provider, with exact
human approval, finite duration/cost bounds, no submit during proposal, and a
durable attempt before POST. Persist the returned job ID before polling; restart
may resume observation, never duplicate submission. Bind provider/code/config
identity, recheck authority before each request/publication, isolate API credentials
from media downloads, and bound/public-address-validate every download destination.

Existing gallery metadata can represent video. Existing MP4 `ftyp` sniffing in
`artifact_store.py` and `media_library.py` does not prove playable content, duration
or dimensions. Generated-image readback is PNG-specific. A bounded video validator,
artifact writer and authenticated readback seam are therefore necessary. `ffprobe`
was not found on this host's PATH in this checkpoint; no decoder was installed.

Open design choices: separately verified local workflow versus initial fixed cloud
protocol; decoder/dependency strategy; exact duration/resolution/cost limits;
download-destination policy and retention; private durable job-ID recovery; and
the connection from `creative/video_pipeline.py` to actual render output. These
are implementation decisions to resolve, not reasons to drop accepted scope.
Local generation, still-image animation, creative assembly and shared arbitrary
media providers remain explicitly open. No network/provider calls or new spend.
