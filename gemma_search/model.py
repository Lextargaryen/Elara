"""EmbeddingGemma 2 Model Management and Inference."""

import os
import sys
import warnings
from typing import Optional, Union, List, Any
import numpy as np

# Suppress noisy warnings
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)
os.environ["TOKENIZERS_PARALLELISM"] = "false"

import torch
from sentence_transformers import SentenceTransformer

from gemma_search.config import DEFAULT_VIDEO_FRAME_BATCH_SIZE

MODEL_ID = "google/embeddinggemma-2"
_GLOBAL_MODEL: Optional[SentenceTransformer] = None


def get_device_info() -> dict:
    """Return hardware accelerator and precision info."""
    cuda_available = torch.cuda.is_available()
    device_name = "cpu"
    device_desc = "CPU"
    dtype = torch.float32

    if cuda_available:
        device_name = "cuda:0"
        device_desc = torch.cuda.get_device_name(0)
        dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float32

    return {
        "cuda_available": cuda_available,
        "device": device_name,
        "device_desc": device_desc,
        "dtype": dtype,
    }


def load_model(verbose: bool = False) -> SentenceTransformer:
    """Load or return the cached EmbeddingGemma 2 SentenceTransformer."""
    global _GLOBAL_MODEL
    if _GLOBAL_MODEL is not None:
        return _GLOBAL_MODEL

    dev_info = get_device_info()
    if verbose:
        print(f"Loading {MODEL_ID} on {dev_info['device_desc']} ({dev_info['dtype']})...")

    model = SentenceTransformer(
        MODEL_ID,
        model_kwargs={"torch_dtype": dev_info["dtype"]},
        device=dev_info["device"],
    )
    _GLOBAL_MODEL = model
    return _GLOBAL_MODEL


def encode_query(query: str, model: Optional[SentenceTransformer] = None) -> np.ndarray:
    """Encode search query using Google's SearchQuery prompt prefix.
    
    Returns normalized 768-d numpy array.
    """
    if model is None:
        model = load_model()

    with torch.inference_mode():
        emb = model.encode(
            query,
            prompt_name="SearchQuery",
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        if isinstance(emb, torch.Tensor):
            emb = emb.detach().cpu().numpy()
        return np.asarray(emb, dtype=np.float32).flatten()


def encode_item(
    item: Any,
    prompt_name: Optional[str] = None,
    model: Optional[SentenceTransformer] = None,
    batch_size: int = DEFAULT_VIDEO_FRAME_BATCH_SIZE,
) -> np.ndarray:
    """Encode a single item (text string, PIL image, audio array, or video frame list).
    
    Returns normalized 768-d numpy array.
    """
    if model is None:
        model = load_model()

    kwargs = {"normalize_embeddings": True, "show_progress_bar": False}
    if prompt_name:
        kwargs["prompt_name"] = prompt_name

    with torch.inference_mode():
        if isinstance(item, list):
            # Video sampled keyframes: encode in bounded mini-batches and mean-pool into single vector
            embs = model.encode(item, batch_size=batch_size, **kwargs)
            if isinstance(embs, torch.Tensor):
                embs = embs.detach().cpu().numpy()
            vec = np.mean(embs, axis=0)
            norm = np.linalg.norm(vec)
            if norm > 0:
                vec = vec / norm
            return np.asarray(vec, dtype=np.float32).flatten()

        emb = model.encode(item, **kwargs)
        if isinstance(emb, torch.Tensor):
            emb = emb.detach().cpu().numpy()
        return np.asarray(emb, dtype=np.float32).flatten()

