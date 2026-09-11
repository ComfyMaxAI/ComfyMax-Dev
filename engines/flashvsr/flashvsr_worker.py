from __future__ import annotations

# Standalone FlashVSR worker for ComfyMax.
#
# This worker keeps FlashVSR in its own Python environment so ComfyMax itself
# does not need Torch/MMGP/Triton/SageAttention installed.
#
# FlashVSR runtime portions adapted from WanGP must retain their original
# copyright/license notices inside the flashvsr package.

import argparse
import gc
import shutil
import subprocess
import sys
import time
from fractions import Fraction
from pathlib import Path

import av
import numpy as np
import torch

from flashvsr.runtime import (
    FlashVSRPaths,
    FLASHVSR_VARIANT_TINY_LONG,
    load_models,
    release_models,
    upscale_video,
)
from mmgp_config import init_pipe


BASE_DIR = Path(__file__).resolve().parent
MODEL_DIR = BASE_DIR / "models"

PROFILE = 4
TCDECODER_TILE_SIZE = 512
TOPK_RATIO = 0.0
SEED = 0
TWO_PASS = False


def emit_progress(percent: int, message: str) -> None:
    percent = max(0, min(100, int(percent)))
    print(f"COMFYMAX_PROGRESS|{percent}|{message}", flush=True)


def emit_result(path: Path) -> None:
    print(f"COMFYMAX_RESULT|{path.resolve()}", flush=True)


def progress_callback(stage, current=None, total=None):
    stage_text = str(stage)
    base_ranges = {
        "Caching": (8, 12),
        "Denoising": (15, 78),
        "TCDecoder Decoding": (70, 84),
        "Color Correction": (84, 86),
    }
    start, end = base_ranges.get(stage_text, (12, 85))

    if current is not None and total not in (None, 0):
        ratio = max(0.0, min(1.0, float(current) / float(total)))
        percent = int(round(start + (end - start) * ratio))
        emit_progress(percent, f"{stage_text} {current}/{total}")
    else:
        emit_progress(start, stage_text)


def find_ffmpeg() -> str:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        return ffmpeg

    local = BASE_DIR / "ffmpeg.exe"
    if local.is_file():
        return str(local)
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError) as exc:
        raise RuntimeError("FFmpeg is missing. Run Install_FlashVSR.bat.") from exc


def read_video(path: Path):
    if not path.is_file():
        raise FileNotFoundError(f"Input video not found: {path}")

    emit_progress(2, "Reading input video")
    container = av.open(str(path))

    try:
        video_stream = container.streams.video[0]
    except IndexError:
        container.close()
        raise RuntimeError("The input file contains no video stream.")

    if video_stream.average_rate is not None:
        fps = float(video_stream.average_rate)
    elif video_stream.base_rate is not None:
        fps = float(video_stream.base_rate)
    else:
        fps = 24.0

    frames = []
    for frame in container.decode(video_stream):
        frames.append(frame.to_ndarray(format="rgb24"))
    container.close()

    if not frames:
        raise RuntimeError("No video frames could be decoded.")

    frame_array = np.stack(frames, axis=0)
    tensor = torch.from_numpy(frame_array).permute(3, 0, 1, 2).contiguous()

    if tensor.dtype != torch.uint8:
        tensor = tensor.to(torch.uint8)

    print(
        f"Input: {tensor.shape[1]} frames, "
        f"{tensor.shape[3]}x{tensor.shape[2]}, {fps:.3f} fps",
        flush=True,
    )

    emit_progress(6, "Input video decoded")
    return tensor, fps


def write_video(frames: torch.Tensor, fps: float, output_path: Path):
    emit_progress(87, "Encoding upscaled video")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if output_path.exists():
        output_path.unlink()

    if frames.device.type != "cpu":
        frames = frames.cpu()

    if frames.dtype != torch.uint8:
        frames = (
            frames.float()
            .clamp(-1.0, 1.0)
            .add(1.0)
            .mul(127.5)
            .round()
            .clamp(0, 255)
            .to(torch.uint8)
        )

    frames = frames.permute(1, 2, 3, 0).contiguous()

    frame_count = int(frames.shape[0])
    height = int(frames.shape[1])
    width = int(frames.shape[2])

    container = av.open(str(output_path), mode="w")
    fps_fraction = Fraction(str(fps)).limit_denominator(100000)

    stream = container.add_stream("libx264", rate=fps_fraction)
    stream.width = width
    stream.height = height
    stream.pix_fmt = "yuv420p"
    stream.options = {"crf": "18", "preset": "medium"}

    for index in range(frame_count):
        frame_np = frames[index].numpy()
        frame = av.VideoFrame.from_ndarray(frame_np, format="rgb24")

        for packet in stream.encode(frame):
            container.mux(packet)

        if index == 0 or (index + 1) % 25 == 0 or index + 1 == frame_count:
            encode_ratio = (index + 1) / max(1, frame_count)
            emit_progress(
                87 + int(round(encode_ratio * 6)),
                f"Encoding frame {index + 1}/{frame_count}",
            )

    for packet in stream.encode():
        container.mux(packet)

    container.close()
    emit_progress(93, "Upscaled video encoded")


def mux_original_audio(
    source_video: Path,
    upscaled_video: Path,
    output_video: Path,
):
    emit_progress(95, "Adding original audio")
    ffmpeg = find_ffmpeg()

    if output_video.exists():
        output_video.unlink()

    command_copy = [
        ffmpeg,
        "-y",
        "-i", str(upscaled_video),
        "-i", str(source_video),
        "-map", "0:v:0",
        "-map", "1:a:0?",
        "-map_metadata", "1",
        "-c:v", "copy",
        "-c:a", "copy",
        "-shortest",
        "-movflags", "+faststart",
        str(output_video),
    ]

    result = subprocess.run(
        command_copy,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    if (
        result.returncode == 0
        and output_video.is_file()
        and output_video.stat().st_size > 0
    ):
        emit_progress(98, "Original audio copied")
        return

    if output_video.exists():
        output_video.unlink()

    command_aac = [
        ffmpeg,
        "-y",
        "-i", str(upscaled_video),
        "-i", str(source_video),
        "-map", "0:v:0",
        "-map", "1:a:0?",
        "-map_metadata", "1",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        "-movflags", "+faststart",
        str(output_video),
    ]

    result = subprocess.run(
        command_aac,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    if (
        result.returncode != 0
        or not output_video.is_file()
        or output_video.stat().st_size == 0
    ):
        raise RuntimeError(
            "FFmpeg could not create the final video with audio.\n\n"
            + result.stderr[-5000:]
        )

    emit_progress(98, "Audio encoded to AAC")


def build_model_paths() -> FlashVSRPaths:
    paths = FlashVSRPaths(
        transformer=str(MODEL_DIR / "FlashVSR_v1.1_transformer_bf16.safetensors"),
        lq_proj=str(MODEL_DIR / "FlashVSR_v1.1_lq_proj_bf16.safetensors"),
        posi_prompt=str(MODEL_DIR / "FlashVSR_v1.1_posi_prompt_bf16.safetensors"),
        tcdecoder=str(MODEL_DIR / "FlashVSR_v1.1_tcdecoder_bf16.safetensors"),
        vae=None,
    )

    required = {
        "transformer": paths.transformer,
        "lq_proj": paths.lq_proj,
        "posi_prompt": paths.posi_prompt,
        "tcdecoder": paths.tcdecoder,
    }

    for name, filename in required.items():
        if not Path(filename).is_file():
            raise FileNotFoundError(f"Missing {name} model: {filename}")

    return paths


def parse_args():
    parser = argparse.ArgumentParser(description="ComfyMax FlashVSR worker")
    parser.add_argument("--input", required=True, help="Input video")
    parser.add_argument("--output", required=True, help="Final output MP4")
    parser.add_argument("--scale", type=float, default=2.0, help="Upscale factor")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    input_video = Path(args.input).resolve()
    output_video = Path(args.output).resolve()
    scale = float(args.scale)

    if scale != 2.0:
        raise ValueError("This integration supports the tested 2x preset only.")

    output_video.parent.mkdir(parents=True, exist_ok=True)

    temp_video = output_video.with_name(
        f".{output_video.stem}_video_only_temp.mp4"
    )

    if temp_video.exists():
        temp_video.unlink()

    sample = None
    output_frames = None

    emit_progress(0, "Starting FlashVSR")

    print(f"Torch   : {torch.__version__}", flush=True)
    print(f"CUDA    : {torch.version.cuda}", flush=True)

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is not available.")

    print(f"GPU     : {torch.cuda.get_device_name(0)}", flush=True)
    print(f"Compute : {torch.cuda.get_device_capability(0)}", flush=True)

    try:
        sample, fps = read_video(input_video)

        input_frames = int(sample.shape[1])
        input_height = int(sample.shape[2])
        input_width = int(sample.shape[3])

        print(
            f"FlashVSR Tiny-Long: {scale:g}x, "
            f"{input_width}x{input_height} -> "
            f"{int(input_width * scale)}x{int(input_height * scale)}, "
            f"{input_frames} frames",
            flush=True,
        )

        model_paths = build_model_paths()

        emit_progress(8, "Loading FlashVSR models")

        load_models(
            model_paths,
            variant=FLASHVSR_VARIANT_TINY_LONG,
            init_pipe=init_pipe,
            profile=PROFILE,
            progress_callback=progress_callback,
        )

        emit_progress(14, "FlashVSR models ready")
        start_time = time.perf_counter()

        output_frames, _ = upscale_video(
            sample,
            scale,
            seed=SEED,
            continue_cache=None,
            return_continue_cache=False,
            vae_tile_size=TCDECODER_TILE_SIZE,
            topk_ratio=TOPK_RATIO,
            still_image=False,
            two_pass=TWO_PASS,
            abort_callback=None,
            progress_callback=progress_callback,
        )

        torch.cuda.synchronize()
        elapsed = time.perf_counter() - start_time

        if output_frames is None:
            raise RuntimeError("FlashVSR returned no output frames.")

        print(
            f"FlashVSR inference complete in {elapsed:.2f} seconds. "
            f"Output tensor: {tuple(output_frames.shape)}",
            flush=True,
        )

        emit_progress(86, "FlashVSR inference complete")
        write_video(output_frames, fps, temp_video)

        output_frames = None
        gc.collect()

        mux_original_audio(input_video, temp_video, output_video)

        if temp_video.exists():
            temp_video.unlink()

        emit_progress(100, "FlashVSR upscale complete")
        emit_result(output_video)
        return 0

    finally:
        try:
            release_models()
        except Exception as exc:
            print(f"Warning while releasing models: {exc}", flush=True)

        sample = None
        output_frames = None
        gc.collect()

        if torch.cuda.is_available():
            torch.cuda.empty_cache()

        if temp_video.exists():
            try:
                temp_video.unlink()
            except OSError:
                pass


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        raise
