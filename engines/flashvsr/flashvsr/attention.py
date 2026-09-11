"""Standalone dense-attention helper for FlashVSR.

This intentionally implements only the modes used by FlashVSR:
- SageAttention 2 when the installed package can provide it.
- PyTorch SDPA as the compatibility/fallback path.

Sparse FlashVSR attention is handled separately by attention_backend.py.
"""

from __future__ import annotations

import torch
import torch.nn.functional as F

try:
    from sageattention import sageattn as _sageattn2
except Exception:
    _sageattn2 = None


def get_supported_attention_modes() -> list[str]:
    modes: list[str] = []
    if _sageattn2 is not None and torch.cuda.is_available():
        modes.append("sage2")
    modes.append("sdpa")
    return modes


def _normalize_mask(attention_mask, q: torch.Tensor, causal: bool):
    if attention_mask is None:
        return None, causal

    if attention_mask.ndim == 4:
        mask = attention_mask.transpose(1, 2)
    elif attention_mask.ndim == 3:
        mask = attention_mask.unsqueeze(1)
    elif attention_mask.ndim == 2:
        mask = attention_mask.unsqueeze(0).unsqueeze(0)
    else:
        mask = attention_mask

    if causal:
        lq, lk = q.shape[1], mask.shape[-1]
        row = torch.arange(lq, device=q.device)[:, None]
        col = torch.arange(lk, device=q.device)[None, :]
        causal_mask = (col <= row).view(1, 1, lq, lk)
        if torch.is_floating_point(mask):
            mask = mask.to(dtype=q.dtype)
            mask = mask.masked_fill(
                ~causal_mask, torch.finfo(mask.dtype).min
            )
        elif mask.dtype == torch.bool:
            mask = mask & causal_mask
        causal = False

    return mask, causal


@torch.compiler.disable()
def _sage2_wrapper(
    qkv_list: list[torch.Tensor],
    *,
    recycle_q: bool = False,
    attention_mask=None,
    causal: bool = False,
) -> torch.Tensor:
    if _sageattn2 is None:
        raise RuntimeError("SageAttention 2 is unavailable.")

    q, k, v = qkv_list
    qkv_list.clear()
    mask, causal = _normalize_mask(attention_mask, q, causal)

    kwargs = {
        "tensor_layout": "NHD",
        "is_causal": causal,
    }

    # The upstream SageAttention API differs slightly between builds.
    # Try WanGP-compatible optional arguments first, then progressively
    # fall back to the common SageAttention 2 signature.
    attempts = [
        dict(kwargs, recycle_q=recycle_q, attn_mask=mask),
        dict(kwargs, attn_mask=mask),
        dict(kwargs),
    ]
    last_exc = None
    for call_kwargs in attempts:
        try:
            return _sageattn2(q, k, v, **call_kwargs)
        except TypeError as exc:
            last_exc = exc

    raise last_exc


@torch.compiler.disable()
def _sdpa_wrapper(
    qkv_list: list[torch.Tensor],
    *,
    attention_mask=None,
    causal: bool = False,
) -> torch.Tensor:
    q, k, v = qkv_list
    qkv_list.clear()

    # FlashVSR tensors arrive as B, tokens, heads, head_dim.
    q = q.transpose(1, 2)
    k = k.transpose(1, 2)
    v = v.transpose(1, 2)

    mask = attention_mask
    if mask is not None:
        if mask.ndim == 3:
            mask = mask.unsqueeze(1)
        elif mask.ndim == 2:
            mask = mask.unsqueeze(0).unsqueeze(0)
        if torch.is_floating_point(mask):
            mask = mask.to(dtype=q.dtype)

    x = F.scaled_dot_product_attention(
        q, k, v,
        attn_mask=mask,
        dropout_p=0.0,
        is_causal=causal,
    )
    return x.transpose(1, 2).contiguous()


@torch.compiler.disable()
def pay_attention(
    qkv_list,
    dropout_p=0.0,
    softmax_scale=None,
    causal=False,
    window_size=(-1, -1),
    deterministic=False,
    version=None,
    force_attention=None,
    attention_mask=None,
    recycle_q=False,
    q_lens=None,
    k_lens=None,
):
    # FlashVSR's current dense calls do not use variable sequence lengths.
    # Fall back to SDPA if they are ever supplied.
    mode = force_attention or "sdpa"
    if mode in ("auto", "sol", None):
        mode = "sage2" if "sage2" in get_supported_attention_modes() else "sdpa"

    if q_lens is not None or k_lens is not None:
        mode = "sdpa"

    if mode in ("sage2", "sage") and _sageattn2 is not None:
        try:
            return _sage2_wrapper(
                qkv_list,
                recycle_q=recycle_q,
                attention_mask=attention_mask,
                causal=causal,
            )
        except (TypeError, RuntimeError) as exc:
            print(f"[FlashVSR] SageAttention dense path unavailable ({exc}); using SDPA.")
            # _sage2_wrapper may have consumed the list, so this fallback is only
            # safe for signature failures before a kernel call. Raise a clear
            # error instead of silently reusing released tensors.
            raise RuntimeError(
                "SageAttention failed after selection. Set MMGP attention to "
                "'sdpa' for compatibility, or install the matching SageAttention wheel."
            ) from exc

    return _sdpa_wrapper(
        qkv_list,
        attention_mask=attention_mask,
        causal=causal,
    )
