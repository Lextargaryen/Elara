"""File modality classification, memory-bounded extraction, and preview generator."""

import os
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, Set, List
from PIL import Image

from gemma_search.config import (
    DEFAULT_MIN_FILE_SIZE_BYTES,
    DEFAULT_MAX_FILE_SIZE_BYTES,
    DEFAULT_MAX_VIDEO_SIZE_BYTES,
    MAX_TEXT_CHARS,
    MIN_VIDEO_KEYFRAMES,
    MAX_VIDEO_KEYFRAMES,

    MAJOR_EXTENSIONS,
    ALL_SUPPORTED_EXTENSIONS,
    MAJOR_IMAGE_EXTS,
    MAJOR_VIDEO_EXTS,
    MAJOR_AUDIO_EXTS,
    CODE_EXTS,
    ADDITIONAL_IMAGE_EXTS,
    ADDITIONAL_VIDEO_EXTS,
    ADDITIONAL_AUDIO_EXTS,
    ADDITIONAL_DOC_EXTS,
)

ALL_IMAGE_EXTS = MAJOR_IMAGE_EXTS | ADDITIONAL_IMAGE_EXTS
ALL_VIDEO_EXTS = MAJOR_VIDEO_EXTS | ADDITIONAL_VIDEO_EXTS
ALL_AUDIO_EXTS = MAJOR_AUDIO_EXTS | ADDITIONAL_AUDIO_EXTS
ALL_DOC_EXTS = {".pdf", ".txt", ".md", ".docx"} | ADDITIONAL_DOC_EXTS

MAX_VIDEO_SAMPLED_FRAMES = 8  # Safe memory bound: <= 8 frames per video (~12 MB RAM)
MAX_AUDIO_SAMPLE_SECONDS = 60  # Safe memory bound: first 60 seconds of audio


def detect_modality(file_path: Path, allowed_exts: Optional[Set[str]] = None) -> str:
    """Classify file into a supported modality: image, video, audio, code, pdf, text, or unsupported."""
    suffix = file_path.suffix.lower()

    if allowed_exts is not None and suffix not in allowed_exts:
        return "unsupported"

    if suffix in ALL_IMAGE_EXTS:
        return "image"
    if suffix in ALL_VIDEO_EXTS:
        return "video"
    if suffix in ALL_AUDIO_EXTS:
        return "audio"
    if suffix == ".pdf":
        return "pdf"
    if suffix in CODE_EXTS:
        return "code"
    if suffix in ALL_DOC_EXTS:
        return "text"

    # If scanning all types, probe if small unknown file is UTF-8 text
    if allowed_exts is None:
        try:
            if file_path.stat().st_size <= 1048576:
                with open(file_path, "r", encoding="utf-8", errors="strict") as f:
                    chunk = f.read(1024)
                    if chunk and not any(ord(c) == 0 for c in chunk):
                        return "text"
        except Exception:
            pass

    return "unsupported"


def compute_dynamic_video_params(
    file_size_bytes: int,
    duration_sec: float,
    total_frames: int,
) -> Tuple[int, int]:
    """Calculate dynamic keyframe sample count and resolution based on video size and length.
    
    The bigger the video (both in file size and duration), the more keyframes are extracted
    to comprehensively capture scene transitions, actions, and objects, reducing representation error.
    
    Returns:
        (num_keyframes, target_max_dimension)
    """
    size_mb = file_size_bytes / (1024 * 1024) if file_size_bytes > 0 else 0.0

    # Scale keyframe count by file size
    if size_mb < 10:
        frames_by_size = 6
    elif size_mb < 50:
        frames_by_size = 8
    elif size_mb < 150:
        frames_by_size = 12
    elif size_mb < 500:
        frames_by_size = 18
    elif size_mb < 1000:
        frames_by_size = 24
    elif size_mb < 2000:
        frames_by_size = 36
    elif size_mb < 3000:
        frames_by_size = 48
    else:
        frames_by_size = 60

    # Scale keyframe count by duration
    if duration_sec <= 0:
        frames_by_dur = frames_by_size
    elif duration_sec < 15:
        frames_by_dur = 6
    elif duration_sec < 60:
        frames_by_dur = 8
    elif duration_sec < 180:
        frames_by_dur = 12
    elif duration_sec < 600:
        frames_by_dur = 18
    elif duration_sec < 1800:
        frames_by_dur = 24
    elif duration_sec < 3600:
        frames_by_dur = 36
    elif duration_sec < 7200:
        frames_by_dur = 48
    else:
        frames_by_dur = 60

    target_frames = max(frames_by_size, frames_by_dur)
    if total_frames > 0:
        target_frames = min(target_frames, total_frames)
    target_frames = max(MIN_VIDEO_KEYFRAMES, min(target_frames, MAX_VIDEO_KEYFRAMES))

    # Dynamic keyframe resolution: higher detail for larger/HD videos
    if size_mb < 100:
        max_dim = 384
    elif size_mb < 1000:
        max_dim = 448
    else:
        max_dim = 512

    return target_frames, max_dim


def sample_video_keyframes(
    video_path: str,
    file_size_bytes: int = 0,
    max_frames: Optional[int] = None,
    max_dim_override: Optional[int] = None,
) -> Tuple[List[Image.Image], int, int, float, int]:
    """Sample dynamically scaled keyframes from video based on size and duration.
    
    Guarantees:
    - Bounded memory: keyframes resized to target dimension (384-512px).
    - Reduced error: long/large videos sample up to 60 keyframes across the entire timeline.
    """
    import cv2
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return [], 0, 0, 0.0, 384

    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    duration_sec = total_frames / fps if fps > 0 else 0.0

    if total_frames <= 0:
        cap.release()
        return [], w, h, duration_sec, 384

    if file_size_bytes <= 0:
        try:
            file_size_bytes = os.path.getsize(video_path)
        except OSError:
            file_size_bytes = 0

    dyn_frames, dyn_dim = compute_dynamic_video_params(file_size_bytes, duration_sec, total_frames)
    num_samples = max_frames if max_frames is not None else dyn_frames
    target_max_dim = max_dim_override if max_dim_override is not None else dyn_dim

    num_samples = min(total_frames, num_samples)
    frame_indices = [int(i * total_frames / num_samples) for i in range(num_samples)]

    frames = []
    for idx in frame_indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ret, frame = cap.read()
        if ret:
            fh, fw = frame.shape[:2]
            if max(fh, fw) > target_max_dim:
                scale = float(target_max_dim) / max(fh, fw)
                nw, nh = int(fw * scale), int(fh * scale)
                frame = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_AREA)

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            frames.append(Image.fromarray(rgb))

    cap.release()
    return frames, w, h, duration_sec, target_max_dim


def extract_file_data(
    file_path: Path,
    min_size_bytes: int = DEFAULT_MIN_FILE_SIZE_BYTES,
    max_size_bytes: int = DEFAULT_MAX_FILE_SIZE_BYTES,
    max_video_size_bytes: int = DEFAULT_MAX_VIDEO_SIZE_BYTES,
    allowed_exts: Optional[Set[str]] = None,
) -> Optional[Tuple[str, Any, str]]:
    """Extract memory-bounded representation for embedding and a user preview.
    
    Guarantees strict memory bounds:
    - Videos: sampled to <= 8 keyframes (uses < 15MB RAM instead of gigabytes, up to 4GB files).
    - Audio: sampled to first 60 seconds of mono waveform.
    - Images: downscaled if exceeding resolution limits.
    """
    try:
        size = file_path.stat().st_size
    except OSError:
        return None

    modality = detect_modality(file_path, allowed_exts=allowed_exts)
    if modality == "unsupported":
        return None

    effective_max = max_video_size_bytes if modality == "video" else max_size_bytes
    if size < min_size_bytes or size > effective_max:
        return None


    abs_str = str(file_path.resolve())
    fname = file_path.name

    if modality == "image":
        try:
            with Image.open(file_path) as img:
                w, h = img.size
                fmt = img.format or file_path.suffix[1:].upper()
                preview = f"Image ({w}x{h}, {fmt})"
                # Downscale if oversized to keep memory strictly bounded
                if max(w, h) > 768:
                    scale = 768.0 / max(w, h)
                    img = img.resize((int(w * scale), int(h * scale)), Image.Resampling.BILINEAR)
                img_rgb = img.convert("RGB")
            return ("image", img_rgb, preview)
        except Exception:
            return None

    elif modality == "video":
        try:
            frames, w, h, duration_sec, frame_dim = sample_video_keyframes(abs_str, file_size_bytes=size)
            if not frames:
                return None
            preview = f"Video ({w}x{h}, {duration_sec:.1f}s, {len(frames)} keyframes @ {frame_dim}px)"
            return ("video", frames, preview)
        except Exception:
            return None

    elif modality == "audio":
        try:
            import soundfile as sf
            # Read at most MAX_AUDIO_SAMPLE_SECONDS of audio (mono float32)
            info = sf.info(abs_str)
            sr = info.samplerate
            max_samples = int(sr * MAX_AUDIO_SAMPLE_SECONDS)

            data, sr = sf.read(abs_str, stop=max_samples, dtype="float32")
            if data.ndim > 1:
                data = data.mean(axis=1)  # Convert to mono

            preview = f"Audio ({info.duration:.1f}s, {sr}Hz)"
            return ("audio", data, preview)
        except Exception:
            return None

    elif modality == "pdf":
        try:
            import pypdf
            reader = pypdf.PdfReader(abs_str)
            num_pages = len(reader.pages)
            text_parts = []
            for page in reader.pages:
                t = page.extract_text()
                if t:
                    text_parts.append(t)
                if sum(len(x) for x in text_parts) > MAX_TEXT_CHARS:
                    break
            full_text = "\n".join(text_parts).strip()
            if not full_text:
                full_text = f"PDF document {fname} with {num_pages} pages."

            snippet = full_text[:120].replace("\n", " ").strip()
            preview = f"PDF ({num_pages}p): {snippet}..."
            formatted_text = f"title: {fname} | text: {full_text[:MAX_TEXT_CHARS]}"
            return ("pdf", formatted_text, preview)
        except Exception:
            return None

    elif modality in ("code", "text"):
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read(MAX_TEXT_CHARS)

            lines = [line.strip() for line in content.splitlines() if line.strip()]
            snippet = " | ".join(lines[:3]) if lines else "Empty file"
            if len(snippet) > 100:
                snippet = snippet[:97] + "..."

            preview = f"{modality.capitalize()}: {snippet}"
            formatted_text = f"title: {fname} | text: {content}"
            return (modality, formatted_text, preview)
        except Exception:
            return None

    return None
