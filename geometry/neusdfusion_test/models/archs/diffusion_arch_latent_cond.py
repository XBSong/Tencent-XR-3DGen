import math
import torch
import torch.nn.functional as F
from torch import nn, einsum 

from einops import rearrange, repeat, reduce
from einops.layers.torch import Rearrange
from einops_exts import rearrange_many, repeat_many, check_shape

from rotary_embedding_torch import RotaryEmbedding

from diff_utils.model_utils import * 

from random import sample


class Cond_embedding(nn.Module):
    def __init__(self, in_dim, out_dim, hidden_dim=768) -> None:
        super().__init__()
        self.model = nn.Sequential(
                                    nn.Linear(in_dim, hidden_dim),
                                    nn.LeakyReLU(),
                                    nn.BatchNorm1d(hidden_dim, hidden_dim),

                                    nn.Linear(hidden_dim, hidden_dim),
                                    nn.LeakyReLU(),
                                    nn.BatchNorm1d(hidden_dim, hidden_dim),

                                    nn.Linear(hidden_dim, hidden_dim),
                                    nn.LeakyReLU(),
                                    nn.BatchNorm1d(hidden_dim, hidden_dim),

                                    nn.Linear(hidden_dim, out_dim),
                                    nn.LeakyReLU()
                                  )
        self.init_weight()

    def init_weight(self):
      for m in self.model.modules():
          if isinstance(m, (torch.nn.Linear, torch.nn.Conv1d, torch.nn.Conv2d)):
              torch.nn.init.xavier_uniform_(m.weight)

    def forward(self, cond):
        return self.model(cond)


class CausalTransformer(nn.Module):
    def __init__(
        self,
        dim, 
        depth,
        dim_in_out=None,
        cross_attn=False,
        dim_head = 64,
        heads = 8,
        ff_mult = 4,
        norm_in = False,
        norm_out = True, 
        attn_dropout = 0.,
        ff_dropout = 0.,
        final_proj = True, 
        normformer = False,
        rotary_emb = True, 
        **kwargs
    ):
        super().__init__()
        self.init_norm = LayerNorm(dim) if norm_in else nn.Identity() # from latest BLOOM model and Yandex's YaLM

        self.rel_pos_bias = RelPosBias(heads = heads)

        rotary_emb = RotaryEmbedding(dim = min(32, dim_head)) if rotary_emb else None
        rotary_emb_cross = RotaryEmbedding(dim = min(32, dim_head)) if rotary_emb else None

        self.layers = nn.ModuleList([])

        dim_in_out = default(dim_in_out, dim)
        self.use_same_dims = (dim_in_out is None) or (dim_in_out==dim)
        image_feature_dim = kwargs.get('image_feature_dim', dim)

        if cross_attn:
            #print("using CROSS ATTN, with dropout {}".format(attn_dropout))
            self.layers.append(nn.ModuleList([
                    Attention(dim = dim_in_out, out_dim=dim, causal = True, dim_head = dim_head, heads = heads, rotary_emb = rotary_emb),
                    Attention(dim = dim, kv_dim=image_feature_dim, causal = True, dim_head = dim_head, heads = heads, dropout = attn_dropout, rotary_emb = rotary_emb_cross),
                    FeedForward(dim = dim, mult = ff_mult, dropout = ff_dropout, post_activation_norm = normformer)
                ]))
            for _ in range(depth):
                self.layers.append(nn.ModuleList([
                    Attention(dim = dim, causal = True, dim_head = dim_head, heads = heads, rotary_emb = rotary_emb),
                    Attention(dim = dim, kv_dim=image_feature_dim, causal = True, dim_head = dim_head, heads = heads, dropout = attn_dropout, rotary_emb = rotary_emb_cross),
                    FeedForward(dim = dim, mult = ff_mult, dropout = ff_dropout, post_activation_norm = normformer)
                ]))
            self.layers.append(nn.ModuleList([
                    Attention(dim = dim, out_dim=dim, causal = True, dim_head = dim_head, heads = heads, rotary_emb = rotary_emb),
                    Attention(dim = dim, kv_dim=image_feature_dim, out_dim=dim_in_out, causal = True, dim_head = dim_head, heads = heads, dropout = attn_dropout, rotary_emb = rotary_emb_cross),
                    FeedForward(dim = dim_in_out, out_dim=dim_in_out, mult = ff_mult, dropout = ff_dropout, post_activation_norm = normformer)
                ]))
        else:
            self.layers.append(nn.ModuleList([
                    Attention(dim = dim_in_out, out_dim=dim, causal = True, dim_head = dim_head, heads = heads, dropout = attn_dropout, rotary_emb = rotary_emb),
                    FeedForward(dim = dim, out_dim=dim, mult = ff_mult, dropout = ff_dropout, post_activation_norm = normformer)
                ]))
            for _ in range(depth):
                self.layers.append(nn.ModuleList([
                    Attention(dim = dim, causal = True, dim_head = dim_head, heads = heads, dropout = attn_dropout, rotary_emb = rotary_emb),
                    FeedForward(dim = dim, mult = ff_mult, dropout = ff_dropout, post_activation_norm = normformer)
                ]))
            self.layers.append(nn.ModuleList([
                    Attention(dim = dim, out_dim=dim_in_out, causal = True, dim_head = dim_head, heads = heads, dropout = attn_dropout, rotary_emb = rotary_emb),
                    FeedForward(dim = dim_in_out, out_dim=dim_in_out, mult = ff_mult, dropout = ff_dropout, post_activation_norm = normformer)
                ]))

        self.norm = LayerNorm(dim_in_out, stable = True) if norm_out else nn.Identity()  # unclear in paper whether they projected after the classic layer norm for the final denoised image embedding, or just had the transformer output it directly: plan on offering both options
        self.project_out = nn.Linear(dim_in_out, dim_in_out, bias = False) if final_proj else nn.Identity()

        self.cross_attn = cross_attn

    def forward(self, x, time_emb=None, context=None):
        n, device = x.shape[1], x.device

        x = self.init_norm(x)

        attn_bias = self.rel_pos_bias(n, n + 1, device = device)

        if self.cross_attn:
            #assert context is not None 
            for idx, (self_attn, cross_attn, ff) in enumerate(self.layers):
                #print("x1 shape: ", x.shape)
                if (idx==0 or idx==len(self.layers)-1) and not self.use_same_dims:
                    x = self_attn(x, attn_bias = attn_bias)
                    x = cross_attn(x, context=context) # removing attn_bias for now 
                else:
                    x = self_attn(x, attn_bias = attn_bias) + x 
                    x = cross_attn(x, context=context) + x  # removing attn_bias for now 
                #print("x2 shape, context shape: ", x.shape, context.shape)
                
                #print("x3 shape, context shape: ", x.shape, context.shape)
                x = ff(x) + x
        
        else:
            for idx, (attn, ff) in enumerate(self.layers):
                #print("x1 shape: ", x.shape)
                if (idx==0 or idx==len(self.layers)-1) and not self.use_same_dims:
                    x = attn(x, attn_bias = attn_bias)
                else:
                    x = attn(x, attn_bias = attn_bias) + x
                #print("x2 shape: ", x.shape)
                x = ff(x) + x
                #print("x3 shape: ", x.shape)

        out = self.norm(x)
        return self.project_out(out)

class DiffusionNetLatentCond(nn.Module):

    def __init__(
        self,
        dim,
        dim_in_out=None,
        num_timesteps = None,
        num_time_embeds = 1,
        cond = None,
        **kwargs
    ):
        super().__init__()
        self.num_time_embeds = num_time_embeds
        self.dim = dim
        self.cond = cond
        self.cross_attn = kwargs.get('cross_attn', False)
        self.cond_dropout = kwargs.get('cond_dropout', False)
        self.image_feature_dim = kwargs.get('image_feature_dim', dim)
        self.drop_cond = kwargs.get("drop_cond", 0.2)
        self.with_cond_embedding = kwargs.get("with_cond_embedding", False)
        self.dim_in_out = default(dim_in_out, dim)
        print("dim, in out, image_feature_dim: ", dim, dim_in_out, self.image_feature_dim)
        print("cond dropout: ", self.cond_dropout)
        print("drop cond:", self.drop_cond)
        print("with_cond_embedding:", self.with_cond_embedding)

        self.to_time_embeds = nn.Sequential(
            nn.Embedding(num_timesteps, self.dim_in_out * num_time_embeds) if exists(num_timesteps) else nn.Sequential(SinusoidalPosEmb(self.dim_in_out), MLP(self.dim_in_out, self.dim_in_out * num_time_embeds)), # also offer a continuous version of timestep embeddings, with a 2 layer MLP
            Rearrange('b (n d) -> b n d', n = num_time_embeds)
        )

        # last input to the transformer: "a final embedding whose output from the Transformer is used to predicted the unnoised CLIP image embedding"
        self.learned_query = nn.Parameter(torch.randn(self.dim_in_out))
        self.causal_transformer = CausalTransformer(dim = dim, dim_in_out=self.dim_in_out, **kwargs)
        if self.with_cond_embedding:
            self.cond_embedding = Cond_embedding(in_dim=self.image_feature_dim, out_dim=self.image_feature_dim, hidden_dim=self.dim)

    def forward(
        self,
        data, 
        diffusion_timesteps,
        pass_cond=-1, # default -1, depends on prob; but pass as argument during sampling
        class_free_weight=None
    ):

        if self.cond:
            assert type(data) is tuple
            data, image_latent = data # adding noise to cond_feature so doing this in diffusion.py
            if self.with_cond_embedding:
                # image_latent += torch.randn(image_latent.shape, device=image_latent.device) * 0.25
                image_latent = self.cond_embedding(image_latent)
            if self.cond_dropout:
                if class_free_weight is None:
                    drop_weight = self.drop_cond
                else:
                    drop_weight = class_free_weight
                # classifier-free guidance: 20% unconditional 
                prob = torch.randint(low=0, high=10, size=(1,))
                percentage = drop_weight
                if prob < percentage or pass_cond==0:
                    cond_feature = torch.zeros_like(image_latent, device=data.device)
                    # cond_feature = torch.zeros( (image_latent.shape[0], image_latent.shape[1], self.image_feature_dim), device=data.device )
                    #print("zeros shape: ", cond_feature.shape) 
                elif prob >= percentage or pass_cond==1:
                    cond_feature = image_latent
                    #print("cond shape: ", cond_feature.shape)
            else:
                cond_feature = image_latent
        cond_feature = cond_feature.unsqueeze(1)
        batch, dim, device, dtype = *data.shape, data.device, data.dtype

        time_embed = self.to_time_embeds(diffusion_timesteps)

        data = data.unsqueeze(1)

        learned_queries = repeat(self.learned_query, 'd -> b 1 d', b = batch)

        model_inputs = [time_embed, data, learned_queries]

        # cond_feature = cond_feature.squeeze()
        # if len(cond_feature.shape) < 2:
        #     cond_feature = cond_feature.unsqueeze(0)
        # # cond = self.cond_embedding(cond)
        # cond_feature = cond_feature.unsqueeze(1)

        if self.cond and not self.cross_attn:
            model_inputs.insert(0, cond_feature) # cond_feature defined in first loop above 
        
        tokens = torch.cat(model_inputs, dim = 1) # (b, 3/4, d); batch and d=512 same across the model_inputs 
        #print("tokens shape: ", tokens.shape)
        if self.cross_attn:
            cond_feature = None if not self.cond else cond_feature
            #print("tokens shape: ", tokens.shape, cond_feature.shape)
            tokens = self.causal_transformer(tokens, context=cond_feature)
        else:
            tokens = self.causal_transformer(tokens)

        # get learned query, which should predict the sdf layer embedding (per DDPM timestep)
        pred = tokens[..., -1, :]

        return pred

