# Music Video Scene Director

Open **Music Video Scene Director** and import the `scenes.json` created by the
standalone music Scene Builder / Audio Chunker. The actual export format is
`format: "comfymax-scenes", version: 1`. It contains project/audio metadata and
scenes with `scene`, `start`, `end`, `duration`, `type`, `audio_source`,
`audio_file`, `start_frame`, `end_frame` and `frames`.

The Director retains every original field and exact source timing. It adds a
`comfymax_director` object at project level for identity and global settings, and
one on each scene for directing choices, workflow inputs, editable prompt,
approval and render tracking. Unknown fields, including unknown Director fields,
survive saving/exporting. Source manifests and WAV files are never overwritten.
Earlier Director draft JSON and SQLite projects remain readable.

The project header shows scene counts, Vocal/Instrumental totals, rendered and
remaining counts, and progress. The compact overview and scene selector show
only one detailed editor at a time. Source timings and types are read-only;
change boundaries in the music Scene Builder and import its new export.

Choose a global video style and optional recurring-character/concept notes.
Choose Artist Action and Camera Action presets or Custom text for each scene.
Preset lists live in `config/music_video_presets.json`.

## Generate and review

Select a mapped workflow per scene. Its fields use the existing mapping files,
model defaults in Settings, and existing LM Studio and ComfyUI clients. Reference
images, audio and video are stored under `data/director_assets` so they survive a
restart. Existing media-upload methods provide mapped assets to ComfyUI. A
`master_audio` field uses the project master song; an `audio` field uses its scene
asset. A mapping without an audio field does not receive audio just because the
project has a WAV or master song. Lyrics corrections/transcriptions are stored
as `comfymax_director.lyrics_override`, preserving original source text and fields.
The existing optional Whisper controls are retained; no new segmentation or
audio-processing system is introduced.

Many real scene durations are fractional, while bundled workflows offer fixed
durations. Exact source duration is added to a fixed option list only if its mapping
explicitly sets `allow_custom_duration: true`. Otherwise choose a render length and explicitly acknowledge any difference.
This saves a render setting without changing source timing or samples. Any
trimming, audio alignment or final assembly remains a separate editing step.

Choose **LM Studio** in **Prompt generator**. **Generate Prompt with LM Studio** sends scene type, source timing, lyrics/context,
global style, artist/camera direction and workflow information through the existing
LM Studio client and H3 prompt instructions. Other mapped workflows receive a
general scene-prompt instruction. Existing model-unload confirmation is preserved.
Generation never queues a render. Review/edit the result, or paste your own.
The existing **Local H3 builder** remains available as an alternative. Both modes
require explicitly allowing replacement before regenerating existing text.
Generation never starts rendering. A failed LM Studio unload blocks rendering
until its saved instance has been unloaded.

**Approve scene prompt** binds approval to the exact prompt, source scene,
global settings, workflow/mapping, reference assets and mapped inputs. Changing
any of those invalidates approval. **Send to ComfyUI** uses the same shared mapped
submission helper as the main generator. It saves the queue ID and server.
**Check render status** retrieves the result, including after an app restart.
An interrupted submission without a saved queue ID requires checking the ComfyUI
queue before allowing another submission.

## Status and persistence

- **New:** no prompt.
- **Prompt Ready:** a prompt exists and the current revision is not approved.
- **Ready to Render:** the current revision is approved. A queued scene also shows
  its job ID/state in the editor; it does not count toward completed progress.
- **Rendered:** ComfyUI reports successful completion with a video output for the
  same approved revision. A queue ID or still-image preview does not qualify.
- **Failed:** the current revision has a failed submission or a confirmed failed
  render/no video output. A transient status-connection error retains the queue ID
  and can be retried without submitting again.

Changes autosave after interactions to `data/music_video_projects.sqlite3`.
**Save Scene** also saves explicitly. Reopen a saved project after restart.
**Download scenes.json with Director state** produces a lossless extended manifest.
Image binaries are stored separately: back up the database and `director_assets`
together; JSON alone does not package images. Missing references must be uploaded
again on another installation. Database and assets are excluded from Git.

No batch rendering, thumbnails, gallery, audio processing or video assembly is
added. Real LM Studio generation and GPU rendering require local service/model
validation; automated tests mock service calls.

## Render recovery and validation (19 September 2026)

Submission persists its intent before contacting ComfyUI, then retains the queue
ID, server, output node and scene revision. **Check render status** can resume
after navigation/restart without submitting again. Connection failures retain
queued status; confirmed execution errors become Failed. Confirmed video output
counts as Rendered even if downloading a local preview fails; retrying the status
check can recover the preview. An ambiguous submission without a queue ID requires
checking the server queue before retrying.

Local videos/last frames now use separate project, scene and job directories;
rerenders and different projects no longer overwrite another scene's video.
Original chunker files and WAV samples are never changed by these operations.

The three Director MiniMax mappings use node 119 for the video VAE and node 120
for the audio VAE. All other pre-existing workflow/model choices are retained.
