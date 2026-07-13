# Camera privacy contract

H31 treats every camera as a local sensor behind an explicit privacy boundary. Importing the
camera package starts nothing. A camera is disabled until the owner enables it and the household
accepts the exact consent-contract version for that camera.

## Non-negotiable boundary

- Camera and VLM endpoints must be loopback or LAN-only. There is no cloud fallback, Frigate+,
  remote analytics, identity service, or external image upload.
- Jarvis does not record video and is not an NVR. Frigate owns RTSP, recording, and detection;
  Jarvis consumes bounded event metadata and, only when necessary, one bounded snapshot.
- Raw snapshot bytes may exist only transiently between the local fetch and the in-memory mask
  transform. They never reach disk, logs, APIs, events, audit records, memory, VLMs, or subscribers.
- Every camera needs at least one valid normalized privacy polygon before a frame can be used.
  Missing or invalid masks, decoder errors, animation, truncation, unsafe image modes, excessive
  dimensions/pixels/bytes, or unverifiable coverage discard the frame.
- Sanitization converts the frame to a new deterministic PNG, blacks every rasterized mask pixel,
  verifies the output pixel-by-pixel, and removes EXIF, GPS, text chunks, thumbnails, and all other
  input metadata before any later stage.
- The only object classes are `person`, `vehicle`, `animal`, and `package`. A person is anonymous.
  Face recognition, identity inference, biometrics, license plates, names, and Frigate sublabels
  are rejected by the event contract rather than redacted after storage.
- Masked snapshots expire after at most 24 hours and camera metadata after at most 30 days. These
  ceilings remain active even if general retention cleanup is disabled.
- Browser and mobile surfaces are metadata-only in H31 v1. They expose no raw frame, clip, private
  snapshot URL, vault identifier, RTSP path, or credential.

## Consent, kill, and revocation

Each operation begins with a lease bound to a camera, the accepted consent version, and an atomic
consent generation. The policy rechecks the camera flag, camera/global kill switch, consent, and
generation before fetch and again before inference, storage, and publication. Masking also checks
both before and after transformation, so revocation during decoding discards the result.

Revocation is fail-closed: stop polling, detach publishers, advance the generation and clear
consent, then request an immediate logical purge. Every old lease becomes stale. Callback failures
are returned explicitly and do not restore consent or allow in-flight work to continue.

## Retention and backups

Expired records become inaccessible before decryption or search and are physically swept on the
next bounded cleanup pass. An explicit camera purge removes all Jarvis-owned camera records.
Separately retained encrypted backups may still contain old ciphertext until their own retention
window expires; Jarvis never represents that ciphertext as live or retrievable camera data.

Rollback is the camera master flag plus consent revocation. That stops Jarvis polling and detaches
its subscribers without changing Frigate, camera firmware, or NVR recordings.
