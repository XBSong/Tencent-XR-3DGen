from dataclasses import dataclass
import math

import torch
import torch.nn as nn
from einops import repeat, rearrange
from transformers import CLIPModel
from torch.nn import functional as F
import numpy as np
import vae
from vae.models.transformers.perceiver_1d import Perceiver
from vae.models.transformers.attention import ResidualCrossAttentionBlock, NormLinearAttention, BasicAttentionBlock
from vae.utils.checkpoint import checkpoint
from vae.utils.base import BaseModule
from vae.utils.typing import *
import random

from .utils import AutoEncoder, FourierEmbedder, get_embedder
from vae.models.transformers.utils import MLP

class PerceiverCrossAttentionEncoder(nn.Module):
    def __init__(self,
                 use_downsample: bool,
                 num_latents: int,
                 embedder: FourierEmbedder,
                 point_feats: int,
                 embed_point_feats: bool,
                 width: int,
                 heads: int,
                 layers: int,
                 init_scale: float = 0.25,
                 qkv_bias: bool = True,
                 use_ln_post: bool = False,
                 use_flash: bool = False,
                 use_checkpoint: bool = False):

        super().__init__()

        self.use_checkpoint = use_checkpoint
        self.num_latents = num_latents
        self.use_downsample = use_downsample
        self.embed_point_feats = embed_point_feats

        if not self.use_downsample:
            self.query = nn.Parameter(torch.randn((num_latents, width)) * 0.02)

        self.embedder = embedder
        if self.embed_point_feats:
            self.input_proj = nn.Linear(self.embedder.out_dim * 2, width)
        else:
            self.input_proj = nn.Linear(self.embedder.out_dim + point_feats, width)

        self.cross_attn = ResidualCrossAttentionBlock(
            width=width,
            heads=heads,
            init_scale=init_scale,
            qkv_bias=qkv_bias,
            use_flash=use_flash,
        )

        self.self_attn = Perceiver(
            n_ctx=num_latents,
            width=width,
            layers=layers,
            heads=heads,
            init_scale=init_scale,
            qkv_bias=qkv_bias,
            use_flash=use_flash,
            use_checkpoint=False
        )

        if use_ln_post:
            self.ln_post = nn.LayerNorm(width)
        else:
            self.ln_post = None

    def _forward(self, pc, feats):
        """

        Args:
            pc (torch.FloatTensor): [B, N, 3]
            feats (torch.FloatTensor or None): [B, N, C]

        Returns:

        """

        bs, N, D = pc.shape
        # breakpoint()
        data = self.embedder(pc)
        if feats is not None:
            if self.embed_point_feats:
                feats = self.embedder(feats)
            data = torch.cat([data, feats], dim=-1)
        
        data = self.input_proj(data)
        
        
        if self.use_downsample:
            ###### fps
            from torch_cluster import fps
            flattened = pc.view(bs*N, D)
            batch = torch.arange(bs).to(pc.device)
            batch = torch.repeat_interleave(batch, N)
            pos = flattened
            ratio = 1.0 * self.num_latents / N
            idx = fps(pos, batch, ratio=ratio)
            query = data.view(bs*N, -1)[idx].view(bs, -1, data.shape[-1])
        else:
            query = self.query
            query = repeat(query, "m c -> b m c", b=bs)

        latents = self.cross_attn(query, data)
        latents = self.self_attn(latents)

        if self.ln_post is not None:
            latents = self.ln_post(latents)

        return latents

    def forward(self, pc: torch.FloatTensor, feats: Optional[torch.FloatTensor] = None):
        """

        Args:
            pc (torch.FloatTensor): [B, N, 3]
            feats (torch.FloatTensor or None): [B, N, C]

        Returns:
            dict
        """

        return checkpoint(self._forward, (pc, feats), self.parameters(), self.use_checkpoint)

class PerceiverCrossAttentionDecoder(nn.Module):

    def __init__(self,
                 num_latents: int,
                 out_dim: int,
                 embedder: FourierEmbedder,
                 width: int,
                 heads: int,
                 init_scale: float = 0.25,
                 qkv_bias: bool = True,
                 use_flash: bool = False,
                 use_checkpoint: bool = False):

        super().__init__()

        self.use_checkpoint = use_checkpoint
        self.embedder = embedder

        self.query_proj = nn.Linear(self.embedder.out_dim, width)

        self.cross_attn_decoder = ResidualCrossAttentionBlock(
            n_data=num_latents,
            width=width,
            heads=heads,
            init_scale=init_scale,
            qkv_bias=qkv_bias,
            use_flash=use_flash
        )

        self.ln_post = nn.LayerNorm(width)
        self.output_proj = nn.Linear(width, out_dim)

    def _forward(self, queries: torch.FloatTensor, latents: torch.FloatTensor):
        queries = self.query_proj(self.embedder(queries))
        x = self.cross_attn_decoder(queries, latents)
        x = self.ln_post(x)
        x = self.output_proj(x)
        return x

    def forward(self, queries: torch.FloatTensor, latents: torch.FloatTensor):
        return checkpoint(self._forward, (queries, latents), self.parameters(), self.use_checkpoint)



@vae.register("michelangelo-autoencoder")
class MichelangeloAutoencoder(AutoEncoder):
    r"""
    A VAE model for encoding shapes into latents and decoding latent representations into shapes.
    """

    @dataclass
    class Config(BaseModule.Config):
        pretrained_model_name_or_path: str = ""
        n_samples: int = 4096
        use_downsample: bool = False
        num_latents: int = 256
        point_feats: int = 0
        embed_point_feats: bool = False
        out_dim: int = 1
        embed_dim: int = 64
        embed_type: str = "fourier"
        num_freqs: int = 8
        include_pi: bool = True
        width: int = 768
        heads: int = 12
        num_encoder_layers: int = 8
        num_decoder_layers: int = 16
        init_scale: float = 0.25
        qkv_bias: bool = True
        use_ln_post: bool = False
        use_flash: bool = False
        use_checkpoint: bool = True
        use_matryoshka: bool = False
        matryoshka_start: int = 16

    cfg: Config

    def configure(self) -> None:
        super().configure()

        self.embedder = get_embedder(embed_type=self.cfg.embed_type, num_freqs=self.cfg.num_freqs, include_pi=self.cfg.include_pi)

        # encoder
        self.cfg.init_scale = self.cfg.init_scale * math.sqrt(1.0 / self.cfg.width)
        self.encoder = PerceiverCrossAttentionEncoder(
            use_downsample=self.cfg.use_downsample,
            embedder=self.embedder,
            num_latents=self.cfg.num_latents,
            point_feats=self.cfg.point_feats,
            embed_point_feats=self.cfg.embed_point_feats,
            width=self.cfg.width,
            heads=self.cfg.heads,
            layers=self.cfg.num_encoder_layers,
            init_scale=self.cfg.init_scale,
            qkv_bias=self.cfg.qkv_bias,
            use_ln_post=self.cfg.use_ln_post,
            use_flash=self.cfg.use_flash,
            use_checkpoint=self.cfg.use_checkpoint
        )

        if self.cfg.embed_dim > 0:
            # VAE embed
            self.pre_kl = nn.Linear(self.cfg.width, self.cfg.embed_dim * 2)
            self.post_kl = nn.Linear(self.cfg.embed_dim, self.cfg.width)
            self.latent_shape = (self.cfg.num_latents, self.cfg.embed_dim)
        else:
            self.latent_shape = (self.cfg.num_latents, self.cfg.width)

        self.transformer = Perceiver(
            n_ctx=self.cfg.num_latents,
            width=self.cfg.width,
            layers=self.cfg.num_decoder_layers,
            heads=self.cfg.heads,
            init_scale=self.cfg.init_scale,
            qkv_bias=self.cfg.qkv_bias,
            use_flash=self.cfg.use_flash,
            use_checkpoint=self.cfg.use_checkpoint
        )

        # decoder
        self.decoder = PerceiverCrossAttentionDecoder(
            embedder=self.embedder,
            out_dim=self.cfg.out_dim,
            num_latents=self.cfg.num_latents,
            width=self.cfg.width,
            heads=self.cfg.heads,
            init_scale=self.cfg.init_scale,
            qkv_bias=self.cfg.qkv_bias,
            use_flash=self.cfg.use_flash,
            use_checkpoint=self.cfg.use_checkpoint
        )
        
        if self.cfg.pretrained_model_name_or_path != "":
            print(f"Loading pretrained model from {self.cfg.pretrained_model_name_or_path}")
            pretrained_ckpt = torch.load(self.cfg.pretrained_model_name_or_path, map_location="cpu")
            if 'state_dict' in pretrained_ckpt:
                _pretrained_ckpt = {}
                for k, v in pretrained_ckpt['state_dict'].items():
                    if k.startswith('shape_model.'):
                        _pretrained_ckpt[k.replace('shape_model.', '')] = v
                pretrained_ckpt = _pretrained_ckpt
            self.load_state_dict(pretrained_ckpt, strict=True)
        
        if self.cfg.use_matryoshka:
            self.nesting_dims = [2**i for i in range(3, int(math.log2(self.cfg.num_latents)) + 1)]
    
    def encode(self,
               surface: torch.FloatTensor,
               sample_posterior: bool = True):
        """
        Args:
            surface (torch.FloatTensor): [B, N, 3+C]
            sample_posterior (bool):

        Returns:
            shape_latents (torch.FloatTensor): [B, num_latents, width]
            kl_embed (torch.FloatTensor): [B, num_latents, embed_dim]
            posterior (DiagonalGaussianDistribution or None):
        """
        # breakpoint()
        assert surface.shape[-1] == 3 + self.cfg.point_feats, f"\
            Expected {3 + self.cfg.point_feats} channels, got {surface.shape[-1]}"
        
        pc, feats = surface[..., :3], surface[..., 3:] # B, n_samples, 3    
        bs, N, D = pc.shape
        
        # very slow
        # if N > self.cfg.n_samples:
        #     # idx = furthest_point_sample(pc, self.cfg.n_samples) # (B, 3, npoint)
        #     # pc = gather_operation(pc, idx).transpose(2, 1).contiguous()
        #     # feats = gather_operation(feats, idx).transpose(2, 1).contiguous()
        #     from torch_cluster import fps
        #     flattened = pc.view(bs*N, D) # bs*N, 64
        #     batch = torch.arange(bs).to(pc.device)
        #     batch = torch.repeat_interleave(batch, N) # bs*N
        #     pos = flattened
        #     ratio = self.cfg.n_samples / N 
        #     idx = fps(pos, batch, ratio=ratio)
        #     pc = pc.view(bs*N, -1)[idx].view(bs, -1, pc.shape[-1])
        #     feats = feats.view(bs*N, -1)[idx].view(bs, -1, feats.shape[-1])

        # print(pc.shape, feats.shape)
        shape_latents = self.encoder(pc, feats) # B, num_latents, width
        kl_embed, posterior = self.encode_kl_embed(shape_latents, sample_posterior)  # B, num_latents, embed_dim

        return shape_latents, kl_embed, posterior


    def decode(self, 
               latents: torch.FloatTensor):
        """
        Args:
            latents (torch.FloatTensor): [B, embed_dim]

        Returns:
            latents (torch.FloatTensor): [B, embed_dim]
        """
        latents = self.post_kl(latents) # [B, num_latents, embed_dim] -> [B, num_latents, width]

        return self.transformer(latents)

    def query(self, 
              queries: torch.FloatTensor, 
              latents: torch.FloatTensor):
        """
        Args:
            queries (torch.FloatTensor): [B, N, 3]
            latents (torch.FloatTensor): [B, embed_dim]

        Returns:
            logits (torch.FloatTensor): [B, N], occupancy logits
        """
        logits = self.decoder(queries, latents).squeeze(-1)
        return logits
    
    def forward(self,
                surface: torch.FloatTensor,
                queries: torch.FloatTensor,
                sample_posterior: bool = True):

        shape_latents, kl_embed, posterior = self.encode(surface, sample_posterior=sample_posterior)
        if self.cfg.use_matryoshka:
            rate = random.randint(self.cfg.matryoshka_start, self.cfg.num_latents)
            
            kl_embed = kl_embed[:,:rate,:]
        latents = self.decode(kl_embed) # [B, num_latents, width]
        logits = self.query(queries, latents) # [B,]
        return shape_latents, latents, posterior, logits





