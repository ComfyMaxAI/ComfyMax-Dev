# ComfyMax Installation

This guide explains the basic installation of ComfyMax on Windows.

## Requirements

Before installing ComfyMax, make sure you already have:

-   Windows 10 or Windows 11
-   NVIDIA GPU
-   64-bit Python 3.11 with the Windows Python launcher
-   ComfyUI installed and working
-   LM Studio installed if you want local prompt generation
-   Git for Windows if you install/update through Git

ComfyMax does not replace ComfyUI or LM Studio. Both services remain
separate local applications.

The ComfyMax setup creates its own `.venv`. FlashVSR uses a second
isolated environment under `engines/flashvsr/env_venv`.

## 1. Download ComfyMax

Open PowerShell and choose the folder where you want to install
ComfyMax.

Clone the repository:

``` powershell
git clone https://github.com/ComfyMaxAI/ComfyMax.git
```

Then open the folder:

``` powershell
cd ComfyMax
```

You can also use a complete source ZIP instead of Git.

## 2. Run the ComfyMax setup

Run:

``` text
Setup_ComfyMax.bat
```

The setup automatically:

-   creates the ComfyMax `.venv` if necessary;
-   installs the Python dependencies from `requirements.txt`;
-   installs `faster-whisper` for local music-video transcription;
-   installs or verifies the FlashVSR runtime when its engine files are
    included.

The normal setup **does not download the large FlashVSR model files**.

If FlashVSR runtime setup fails, core ComfyMax and Whisper can still be
used. FlashVSR can be repaired later.

## 3. Optional: download FlashVSR models

Only users who want FlashVSR video upscaling need this step.

Run:

``` text
Download_FlashVSR_Models.bat
```

The downloader installs the four compatible FlashVSR v1.1 BF16 model
files into:

``` text
engines\flashvsr\models
```

It verifies SHA-256 checksums and reuses existing files only when they
are valid.

The model download is roughly 3.5 GB.

To repair only the FlashVSR runtime, use:

``` text
Install_FlashVSR.bat
```

To check an existing runtime:

``` powershell
.\Install_FlashVSR.bat --check
```

## 4. Test ComfyUI first

Before using ComfyMax, open ComfyUI and test the example workflow
supplied in:

``` text
workflow_example
```

This confirms that:

-   the required custom nodes are installed;
-   the required ComfyUI models are available;
-   the workflow itself works correctly.

If the example does not work directly in ComfyUI, fix that before trying
it through ComfyMax.

## 5. Start LM Studio

Start LM Studio and enable its local server if you want ComfyMax to
generate prompts.

The default ComfyMax configuration expects LM Studio at:

``` text
http://127.0.0.1:1234
```

You can change the address later in ComfyMax Settings.

LM Studio receives prompt text and supported reference images. ComfyMax
does not send audio or video files to the LM Studio chat endpoint.

## 6. Start ComfyUI

Start ComfyUI normally.

The default address is:

``` text
http://127.0.0.1:8188
```

If your installation uses another address or port, change it in
ComfyMax.

## 7. Start ComfyMax

Run:

``` text
Start_ComfyMax.bat
```

ComfyMax should open in your browser at:

``` text
http://localhost:8501
```

If startup reports that port 8501 is unavailable, first check whether
another ComfyMax/Streamlit instance is already running.

## 8. Configure ComfyMax

Open **Settings** and configure:

-   ComfyUI address
-   LM Studio address
-   workflow model selections
-   ComfyUI output folder

The output folder is also used by Video Gallery and FlashVSR.

## 9. Whisper transcription

`faster-whisper` is installed automatically by `Setup_ComfyMax.bat`.

In Music Video Scene Director, vocal scene audio can be transcribed
locally. The transcript remains editable and can be stored as the scene
lyrics before LM Studio creates the H3 prompt.

ComfyMax can try GPU transcription and fall back to CPU when the
required Whisper CUDA libraries are unavailable. CPU fallback is slower
but requires no separate CUDA modification for normal short-scene
transcription.

No separate Whisper installation command should normally be necessary.

## 10. Add your own ComfyUI workflow

ComfyMax includes **Workflow Mapper**.

Export your workflow from ComfyUI using:

``` text
Export (API Format)
```

Then open **Workflow Mapper** in ComfyMax.

The Mapper can:

-   analyze the workflow;
-   detect important controls;
-   suggest mappings;
-   detect reference-image inputs;
-   validate the mapping;
-   install the workflow and matching mapping into ComfyMax.

The workflow and mapping must use matching filenames.

## Updating ComfyMax

For a Git installation, run:

``` text
Update_ComfyMax.bat
```

The updater:

-   checks GitHub for updates;
-   protects locally modified tracked files;
-   leaves untracked user files alone;
-   downloads the latest ComfyMax version;
-   updates the Python dependencies from `requirements.txt`.

Because `faster-whisper` is part of `requirements.txt`, Whisper remains
part of the normal ComfyMax dependency installation.

FlashVSR models remain optional and separate. Existing valid model files
do not need to be downloaded again.

## Important folders

``` text
workflows
```

Contains ComfyUI API workflows used by ComfyMax.

``` text
config/workflow_mappings
```

Contains the matching ComfyMax mapping files.

``` text
workflow_example
```

Contains example workflows that should be tested directly in ComfyUI.

``` text
engines/flashvsr/env_venv
```

Contains the isolated FlashVSR runtime.

``` text
engines/flashvsr/models
```

Contains the optional FlashVSR model files.

``` text
data
```

Contains local ComfyMax application data such as saved prompt
information and project state.

## Quick installation summary

For most users:

``` text
1. Install/prepare ComfyUI
2. Install/prepare LM Studio if prompt generation is wanted
3. Run Setup_ComfyMax.bat
4. Start ComfyUI
5. Start LM Studio if needed
6. Run Start_ComfyMax.bat
```

Only if FlashVSR upscaling is wanted:

``` text
7. Run Download_FlashVSR_Models.bat
```

Whisper requires no separate installation step.

## More information

See `README.md` for the full feature overview, Music Video Scene
Director, Whisper transcription, FlashVSR, Workflow Mapper, Prompt
Library, Video Gallery and troubleshooting.
