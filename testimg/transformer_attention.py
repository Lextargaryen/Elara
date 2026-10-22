import torch
import torch.nn as nn
import math

class MultiHeadAttention(nn.Module):
    """Multi-head scaled dot-product attention module."""
    def __init__(self, d_model: int = 512, n_heads: int = 8):
        super().__init__()
        self.d_model = d_model
        self.n_heads = n_heads
        self.head_dim = d_model // n_heads
        self.q_proj = nn.Linear(d_model, d_model)
        self.k_proj = nn.Linear(d_model, d_model)
        self.v_proj = nn.Linear(d_model, d_model)
        self.out_proj = nn.Linear(d_model, d_model)

    def forward(self, query, key, value, mask=None):
        B, L, _ = query.shape
        q = self.q_proj(query).view(B, L, self.n_heads, self.head_dim).transpose(1, 2)
        k = self.k_proj(key).view(B, -1, self.n_heads, self.head_dim).transpose(1, 2)
        v = self.v_proj(value).view(B, -1, self.n_heads, self.head_dim).transpose(1, 2)
        scores = torch.matmul(q, k.transpose(-2, -1)) / math.sqrt(self.head_dim)
        if mask is not None:
            scores = scores.masked_fill(mask == 0, -1e9)
        attn_weights = torch.softmax(scores, dim=-1)
        out = torch.matmul(attn_weights, v)
        out = out.transpose(1, 2).contiguous().view(B, L, self.d_model)
        return self.out_proj(out)
