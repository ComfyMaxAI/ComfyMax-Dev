# ComfyMax

ComfyMax is a local Windows interface for preparing MiniMax H3 video
prompts, reviewing them before rendering in ComfyUI, building
music-video scenes, transcribing vocal scenes locally with Whisper, and
browsing or upscaling results. It uses Streamlit for the interface and
can use LM Studio to turn a scene idea into a structured prompt. You can
also paste a finished prompt and skip LM Studio.

This README describes the current development files, including local
**faster-whisper** transcription and the optional **FlashVSR v1.1
Tiny-Long 2x** upscaler. It does not assign a new release number.

## What's included in this version

-   **Windows setup:** `Setup_ComfyMax.bat` creates the ComfyMax
    environment, installs its Python dependencies, including
    `faster-whisper`, and installs or verifies the isolated FlashVSR
    runtime when the engine files are present.
-   **Local Whisper transcription:** vocal scene audio can be
    transcribed locally with faster-whisper. ComfyMax tries NVIDIA CUDA
    where usable and can fall back to CPU for systems without the
    required Whisper CUDA runtime libraries.
-   **Optional FlashVSR v1.1:** the FlashVSR runtime is kept in its own
    environment. The large model files are installed separately with
    `Download_FlashVSR_Models.bat`, with SHA-256 verification and reuse
    of already valid files.
-   **LM Studio model management:** checks loaded instances before
    loading; reuses the requested model when possible; asks before
    unloading different or multiple loaded models.
-   **Local Prompt Library:** explicitly save approved prompts, search
    and filter them, reuse them for another render, and delete with
    confirmation.
-   **Music Video Scene Director:** import Scene Builder `scenes.json`,
    use vocals-derived scene audio, transcribe vocal scenes, direct and
    generate editable prompts per scene, approve and render through
    mapped workflows, and persist progress and output references.
-   **Scene Builder:** compose characters, action, ordered dialogue
    turns, ending, camera and lighting before generating a final prompt.
-   **Video Gallery:** browse output subfolders, play, search, filter,
    sort, download, open files in Explorer and delete with confirmation.
-   **Workflow Mapper:** inspect an API workflow, review suggested
    mappings and install the workflow with its matching mapping.
-   **Text-only and reference-image workflow mappings**, prompt
    approval, mapped render controls and an NVIDIA GPU monitor.

## Install and start

### 1. Prepare your computer

Use Windows with **64-bit Python 3.11 and the Windows Python launcher**
installed. The setup scripts use `py -3.11`; they do not install Python
itself.

You also need:

-   A working **ComfyUI** installation with the nodes and models
    required by your chosen workflow.
-   **LM Studio** with a downloaded model and its local API server
    enabled if you want prompt generation. Use a vision-capable model
    when asking it to interpret reference images.
-   **Git for Windows** if you clone the project or use its Git updater.
    An extracted source ZIP can be used without Git.
-   An NVIDIA GPU and working drivers for the included GPU monitoring
    and the current FlashVSR integration.

ComfyMax does not install ComfyUI, LM Studio, their models or ComfyUI
custom nodes.

### 2. Get ComfyMax

Extract the complete project archive into a writable folder, or clone
the repository:

``` powershell
git clone https://github.com/ComfyMaxAI/ComfyMax.git
cd ComfyMax
```

Keep the project folders together; copying only `App.py` or one
installer is insufficient.

### 3. Run ComfyMax setup

Double-click **`Setup_ComfyMax.bat`** in the main ComfyMax folder, or
run:

``` powershell
.\Setup_ComfyMax.bat
```

The setup:

1.  Creates `.venv` when it does not exist.
2.  Installs the dependencies in `requirements.txt`, including
    `faster-whisper`.
3.  Installs or verifies the isolated FlashVSR runtime when
    `engines/flashvsr` is present.
4.  Does **not** download the large FlashVSR model files.

A FlashVSR runtime failure does not prevent the core ComfyMax and
Whisper installation from completing. FlashVSR can be repaired later
with `Install_FlashVSR.bat`.

### 4. Optional: install FlashVSR models

FlashVSR model files are deliberately separate from the normal ComfyMax
setup.

Run:

``` powershell
.\Download_FlashVSR_Models.bat
```

The model installer reads `engines/flashvsr/models.json`, downloads
missing model files and verifies their SHA-256 hashes. Existing files
are reused only when their checksum is valid.

The four required files are:

``` text
engines/
└── flashvsr/
    └── models/
        ├── FlashVSR_v1.1_transformer_bf16.safetensors
        ├── FlashVSR_v1.1_lq_proj_bf16.safetensors
        ├── FlashVSR_v1.1_posi_prompt_bf16.safetensors
        └── FlashVSR_v1.1_tcdecoder_bf16.safetensors
```

The compatible BF16 conversions are defined by `models.json`. Do not
rename unrelated official `.ckpt` or `.pth` files to these names.

### 5. Test the example directly in ComfyUI

Open the supplied workflow from `workflow_example/` in ComfyUI. Install
any missing nodes, select the required models and complete a render
there first.

If the workflow does not work directly in ComfyUI, fix that before
trying it through ComfyMax.

### 6. Start the services and interface

Start ComfyUI. Start the LM Studio local server if using prompt
generation.

Default addresses:

  Service     Address
  ----------- -------------------------
  ComfyUI     `http://127.0.0.1:8188`
  LM Studio   `http://127.0.0.1:1234`
  ComfyMax    `http://localhost:8501`

Run:

``` text
Start_ComfyMax.bat
```

If port `8501` is already in use, check whether another
ComfyMax/Streamlit instance is still running before starting another
one.

### 7. Configure ComfyMax

Open **Settings** and save your service URLs, workflow model selections
and existing **ComfyUI output folder**.

For example, if your output folder is:

``` text
D:\ComfyUI\ComfyUI\output
```

select that folder and use **Test output folder**. The Gallery and
FlashVSR output use this configured location.

## Music Video Scene Director and Whisper

The Music Video Scene Director can work with scenes exported from the
music-video preparation workflow.

For vocal scenes, ComfyMax can:

1.  Locate the scene audio.
2.  Transcribe it locally with faster-whisper.
3.  Store the editable transcript as the scene lyrics.
4.  Include the exact lyrics in the LM Studio instruction for the final
    MiniMax H3 prompt.
5.  Send the actual mapped audio separately to ComfyUI where the
    selected workflow supports audio.

Audio and video files are **not** sent to LM Studio. LM Studio receives
text and supported reference images only.

For Whisper, ComfyMax can attempt GPU transcription and fall back to CPU
when the required CUDA libraries for faster-whisper are unavailable. CPU
fallback is slower but avoids requiring users to manually modify their
CUDA installation for short scene transcription.

## Make your first video

1.  Select a workflow.
2.  Upload the reference images required by its mapping.
3.  Enter a scene idea, optionally prepared with Scene Builder or Music
    Video Scene Director.
4.  Select an LM Studio model and generate the H3 prompt, or paste
    finished text into **Final prompt**.
5.  Review and edit the final text, then approve it.
6.  Set the controls exposed by the workflow mapping and send the
    approved prompt to ComfyUI.
7.  Review the result in **Video Gallery**.

Generating a prompt does not start a render.

## LM Studio and GPU memory

Before loading a model, ComfyMax queries LM Studio for loaded instances.
If a different model or several models are loaded, ComfyMax can ask
before unloading them.

The prompt-generation flow can unload its LM Studio model afterward.
ComfyUI models may remain loaded for repeated renders. Use the available
unload controls when you need to free VRAM.

## Save and reuse prompts

After approval, choose **Save approved prompt**. Approval by itself does
not save it.

Prompt Library supports searching and filtering saved entries and
reusing their text. Reuse does not automatically start generation or
rendering.

Entries are stored locally in:

``` text
data/prompt_library.sqlite3
```

Stop ComfyMax before copying that database for backup.

## FlashVSR runtime and models

FlashVSR has two deliberately separate components.

### Runtime

The runtime lives in:

``` text
engines/flashvsr/env_venv
```

`Setup_ComfyMax.bat` installs or verifies it during normal setup when
the FlashVSR engine files are available.

To install or repair only the runtime:

``` powershell
.\Install_FlashVSR.bat
```

To verify an already installed runtime without reinstalling
dependencies:

``` powershell
.\Install_FlashVSR.bat --check
```

The current runtime check verifies the isolated environment, pinned
runtime imports, CUDA availability and FFmpeg. It does not require the
model files.

### Models

Models live in:

``` text
engines/flashvsr/models
```

Install them separately with:

``` powershell
.\Download_FlashVSR_Models.bat
```

The downloader can safely be run again. Valid files are reused; missing
or invalid files are downloaded again and checked against the recorded
SHA-256 values.

The model files total roughly **3.5 GB**, so keeping them outside the
normal setup avoids forcing every ComfyMax user to download FlashVSR
weights.

### Upscale a video

Save the existing ComfyUI output folder in **Settings**, then open
**FlashVSR Upscaler**, upload a video and start upscaling.

The page distinguishes between the FlashVSR **runtime** and **models**,
so a missing model installation can be reported separately from a broken
runtime.

Results are saved under:

``` text
<ComfyUI output folder>\videos\upscaled
```

The preserved FlashVSR preset is Tiny-Long, 2x scale, MMGP profile 4,
TCDecoder tiles 512, top-k 0 (automatic), seed 0 and Two Pass off.

## Add workflows and manage files

Export your working ComfyUI graph in **API Format**, open **Workflow
Mapper**, upload it and review the suggested controls and compatibility
warnings.

The API workflow in `workflows/` and its mapping in
`config/workflow_mappings/` must have the same filename.

  -----------------------------------------------------------------------
  Location                            Purpose
  ----------------------------------- -----------------------------------
  `App.py`, `pages/`, `modules/`      Interface and application code

  `.venv/`                            ComfyMax interface environment

  `config/app.json`                   Service configuration

  `config/settings.json`              Saved settings

  `config/workflow_mappings/`,        Paired mappings and API workflows
  `workflows/`                        

  `workflow_example/`                 Examples to test directly in
                                      ComfyUI

  `data/prompt_library.sqlite3`       Saved prompt library

  `engines/flashvsr/env_venv/`        Separate FlashVSR runtime

  `engines/flashvsr/models/`          Optional FlashVSR model files
  -----------------------------------------------------------------------

## Updating ComfyMax

For a Git installation, run:

``` text
Update_ComfyMax.bat
```

The updater checks GitHub for updates, protects locally modified tracked
files, leaves untracked user files alone and updates the Python
dependencies from `requirements.txt`.

Because `faster-whisper` is now in `requirements.txt`, dependency
updates also keep the Whisper package available.

FlashVSR models remain a separate optional download and should not need
to be downloaded again when their existing hashes are valid.

## Troubleshooting

  -----------------------------------------------------------------------
  Problem                             What to check
  ----------------------------------- -----------------------------------
  Python launcher or Python 3.11      Install 64-bit Python 3.11 with the
  missing                             Windows launcher and retry setup.

  Port 8501 unavailable               Check whether ComfyMax/Streamlit is
                                      already running.

  ComfyMax cannot render              Run the example directly in ComfyUI
                                      and resolve missing nodes/models
                                      first.

  LM Studio prompt error with media   Audio/video must not be sent to LM
                                      Studio; only supported images and
                                      text should be supplied.

  Whisper GPU transcription fails     ComfyMax can fall back to CPU; CPU
                                      transcription is slower but avoids
                                      a manual CUDA-runtime requirement.

  FlashVSR runtime missing/broken     Run `Install_FlashVSR.bat`.

  FlashVSR models missing             Run `Download_FlashVSR_Models.bat`.

  FlashVSR model download/checksum    Check network access and disk
  fails                               space, then rerun the model BAT.
                                      Verified files are reused.

  FlashVSR reports another setup      Wait for it. If setup was forcibly
  running                             interrupted and none is running,
                                      remove
                                      `engines/flashvsr/.setup.lock` and
                                      retry.

  FlashVSR CUDA/import check fails    Repair the runtime and verify
                                      GPU/driver compatibility; run
                                      `Install_FlashVSR.bat --check`.

  Gallery is empty                    Save/test the correct ComfyUI
                                      output folder, clear filters and
                                      refresh.

  GPU monitor unavailable             Check that `nvidia-smi` works.
  -----------------------------------------------------------------------

## Credits and license information

ComfyMax integrates ComfyUI, LM Studio and MiniMax H3 workflows.
FlashVSR runtime portions come from Wan2GP; retain their existing
notices. Third-party components and model sources have their own
licenses and terms.

Before distributing a release, make sure the root `LICENSE` contains the
complete intended license text and that third-party notices are
retained.
