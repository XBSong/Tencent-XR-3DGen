import math
import copy
import torch
from torch import nn, einsum
import torch.nn.functional as F
from inspect import isfunction
from collections import namedtuple
from functools import partial

from einops import rearrange, reduce
from einops.layers.torch import Rearrange

#from model.diffusion.model import * 
from diff_utils.helpers import * 

import numpy as np
import os
from statistics import mean
from tqdm.auto import tqdm
import open3d as o3d


# constants
ModelPrediction =  namedtuple('ModelPrediction', ['pred_noise', 'pred_x_start'])


class DiffusionModelVectorUncond(nn.Module):
    def __init__(
        self,
        model,
        timesteps = 1000, sampling_timesteps = None, beta_schedule = 'cosine',
        loss_type = 'l2', objective = 'pred_x0', 
        data_scale = 1.0, data_shift = 0.0,
        p2_loss_weight_gamma = 0., # p2 loss weight, from https://arxiv.org/abs/2204.00227 - 0 is equivalent to weight of 1 across time - 1. is recommended
        p2_loss_weight_k = 1,
        ddim_sampling_eta = 1.
    ):
        super().__init__()

        self.model = model
        self.objective = objective

        betas = linear_beta_schedule(timesteps) if beta_schedule == 'linear' else cosine_beta_schedule(timesteps)
        alphas = 1. - betas
        alphas_cumprod = torch.cumprod(alphas, axis=0)
        alphas_cumprod_prev = F.pad(alphas_cumprod[:-1], (1, 0), value = 1.)

        timesteps, = betas.shape
        self.num_timesteps = int(timesteps)

        self.loss_fn = F.l1_loss if loss_type=='l1' else F.mse_loss

        # sampling related parameters
        self.sampling_timesteps = default(sampling_timesteps, timesteps) # default num sampling timesteps to number of timesteps at training
        assert self.sampling_timesteps <= timesteps
        self.ddim_sampling_eta = ddim_sampling_eta
        
        # self.register_buffer('data_scale', torch.tensor(data_scale))
        # self.register_buffer('data_shift', torch.tensor(data_shift))

        # helper function to register buffer from float64 to float32
        register_buffer = lambda name, val: self.register_buffer(name, val.to(torch.float32))
        

        register_buffer('betas', betas)
        register_buffer('alphas_cumprod', alphas_cumprod)
        register_buffer('alphas_cumprod_prev', alphas_cumprod_prev)

        # calculations for diffusion q(x_t | x_{t-1}) and others
        register_buffer('sqrt_alphas_cumprod', torch.sqrt(alphas_cumprod))
        register_buffer('sqrt_one_minus_alphas_cumprod', torch.sqrt(1. - alphas_cumprod))
        register_buffer('log_one_minus_alphas_cumprod', torch.log(1. - alphas_cumprod))
        register_buffer('sqrt_recip_alphas_cumprod', torch.sqrt(1. / alphas_cumprod))
        register_buffer('sqrt_recipm1_alphas_cumprod', torch.sqrt(1. / alphas_cumprod - 1))

        # calculations for posterior q(x_{t-1} | x_t, x_0)
        posterior_variance = betas * (1. - alphas_cumprod_prev) / (1. - alphas_cumprod)
        # above: equal to 1. / (1. / (1. - alpha_cumprod_tm1) + alpha_t / beta_t)
        register_buffer('posterior_variance', posterior_variance)
        # below: log calculation clipped because the posterior variance is 0 at the beginning of the diffusion chain
        register_buffer('posterior_log_variance_clipped', torch.log(posterior_variance.clamp(min =1e-20)))
        register_buffer('posterior_mean_coef1', betas * torch.sqrt(alphas_cumprod_prev) / (1. - alphas_cumprod))
        register_buffer('posterior_mean_coef2', (1. - alphas_cumprod_prev) * torch.sqrt(alphas) / (1. - alphas_cumprod))
        
        # calculate p2 reweighting
        register_buffer('p2_loss_weight', (p2_loss_weight_k + alphas_cumprod / (1 - alphas_cumprod)) ** -p2_loss_weight_gamma)

    def predict_start_from_noise(self, x_t, t, noise):
        return (
            extract(self.sqrt_recip_alphas_cumprod, t, x_t.shape) * x_t -
            extract(self.sqrt_recipm1_alphas_cumprod, t, x_t.shape) * noise
        )

    def predict_noise_from_start(self, x_t, t, x0):
        return (
            (x0 - extract(self.sqrt_recip_alphas_cumprod, t, x_t.shape) * x_t) / \
            extract(self.sqrt_recipm1_alphas_cumprod, t, x_t.shape)
        )

    @torch.no_grad()
    def ddim_sample(self, dim, batch_size, noise=None, clip_denoised = True, traj=False, cond=None, class_free_weight=0):
        batch, device, total_timesteps, sampling_timesteps, eta, objective = batch_size, self.betas.device, self.num_timesteps, self.sampling_timesteps, self.ddim_sampling_eta, self.objective
        times = torch.linspace(0., total_timesteps, steps = sampling_timesteps + 2)[:-1]
        times = list(reversed(times.int().tolist()))
        time_pairs = list(zip(times[:-1], times[1:]))

        traj = []

        x_T = default(noise, torch.randn(batch, dim, device = device)) 

        for time, time_next in tqdm(time_pairs, desc = 'sampling loop time step'):
            alpha = self.alphas_cumprod_prev[time]
            alpha_next = self.alphas_cumprod_prev[time_next]

            time_cond = torch.full((batch,), time, device = device, dtype = torch.long)

            model_input = (x_T, cond) if cond is not None else x_T
            pred_noise, x_start, *_ = self.model_predictions(model_input, time_cond)

            if clip_denoised:
                x_start.clamp_(-1., 1.)

            sigma = eta * ((1 - alpha / alpha_next) * (1 - alpha_next) / (1 - alpha)).sqrt()
            c = ((1 - alpha_next) - sigma ** 2).sqrt()

            noise = torch.randn_like(x_T) if time_next > 0 else 0.

            x_T = x_start * alpha_next.sqrt() + \
                  c * pred_noise + \
                  sigma * noise
            
            traj.append(x_T.clone())
    
        if traj:
            return x_T, traj
        else:
            return x_T

    @torch.no_grad()
    def sample(self, dim, batch_size, noise=None, clip_denoised = "static", traj=False, cond=None, class_free_weight=0):
        """
        clip_denoised: static or dynamic, default: "static"
        """
        batch, device, objective = batch_size, self.betas.device, self.objective

        traj = []

        x_T = default(noise, torch.randn(batch, dim, device = device))

        for t in reversed(range(0, self.num_timesteps)):
            
            time_cond = torch.full((batch,), t, device = device, dtype = torch.long)

            model_input = (x_T, cond) if cond is not None else x_T
            pred_noise, x_start, *_ = self.model_predictions(model_input, time_cond, class_free_weight=class_free_weight)
            if clip_denoised == "static":
                x_start.clamp_(-1., 1.)
            elif clip_denoised == "dynamic":
                s = np.percentile(x_start, 99.5, tuple(range(1, x_start.dim())))
                s = torch.tensor([max(x, 1.0) for x in s], device=x_start.device)
                if x_start.dim() == 2:
                    s = s[:, None]
                elif x_start.dim() == 4:
                    s = s[:, None, None, None]
                x_start = torch.clip(x_start, -s, s) / s
            model_mean, _, model_log_variance = self.q_posterior(x_start = x_start, x_t = x_T, t = time_cond)

            noise = torch.randn_like(x_T) if t > 0 else 0. # no noise if t == 0

            x_T = model_mean + (0.5 * model_log_variance).exp() * noise
            
            traj.append(x_T.clone())
    
        if traj:
            return x_T, traj
        else:
            return x_T

    def q_posterior(self, x_start, x_t, t):
        posterior_mean = (
            extract(self.posterior_mean_coef1, t, x_t.shape) * x_start +
            extract(self.posterior_mean_coef2, t, x_t.shape) * x_t
        )
        posterior_variance = extract(self.posterior_variance, t, x_t.shape)
        posterior_log_variance_clipped = extract(self.posterior_log_variance_clipped, t, x_t.shape)
        return posterior_mean, posterior_variance, posterior_log_variance_clipped


    # "nice property": return x_t given x_0, noise, and timestep
    def q_sample(self, x_start, t, noise=None):
        
        noise = default(noise, lambda: torch.randn_like(x_start))
        #noise = torch.clamp(noise, min=-6.0, max=6.0)

        return (
            extract(self.sqrt_alphas_cumprod, t, x_start.shape) * x_start +
            extract(self.sqrt_one_minus_alphas_cumprod, t, x_start.shape) * noise
        )

    # main function for calculating loss
    def forward(self, x_start, t, ret_pred_x=False, noise = None, cond=None):
        '''
        x_start: [B, D]
        t: [B]
        '''

        noise = default(noise, lambda: torch.randn_like(x_start)) 

        x = self.q_sample(x_start=x_start, t=t, noise=noise) 

        model_out = self.model(x, t)

        if self.objective == 'pred_noise':
            target = noise
        elif self.objective == 'pred_x0':
            target = x_start
        else:
            raise ValueError(f'unknown objective {self.objective}')

        loss = self.loss_fn(model_out, target, reduction = 'none')
        #loss = reduce(loss, 'b ... -> b (...)', 'mean', b = x_start.shape[0]) # only one dim of latent so don't need this line 
        
        loss = loss * extract(self.p2_loss_weight, t, loss.shape)
        unreduced_loss = loss.detach().clone().mean(dim=1)
        
        
        if ret_pred_x:
            # print(loss, loss.mean())
            return loss.mean(), x, target, model_out, unreduced_loss
        else:
            return loss.mean(), unreduced_loss

    def model_predictions(self, model_input, t, class_free_weight=0):
        
        #model_output1 = self.model(model_input, t, pass_cond=0)
        #model_output2 = self.model(model_input, t, pass_cond=1)
        #model_output = model_output2*5 - model_output1*4
        model_output = self.model(model_input, t, pass_cond=-1, class_free_weight=class_free_weight)

        x = model_input[0] if type(model_input) is tuple else model_input

        if self.objective == 'pred_noise':
            pred_noise = model_output
            x_start = self.predict_start_from_noise(x, t, model_output)

        elif self.objective == 'pred_x0':
            pred_noise = self.predict_noise_from_start(x, t, model_output)
            x_start = model_output

        return ModelPrediction(pred_noise, x_start)


    
    # a wrapper function that only takes x_start (clean modulation vector) and condition
    # does everything including sampling timestep and returns loss, loss_100, loss_1000, prediction
    def diffusion_model_from_latent(self, x_start, cond=None):

        # STEP 1: sample timestep 
        t = torch.randint(0, self.num_timesteps, (x_start.shape[0],), device=x_start.device).long()

        # STEP 3: pass to forward function
        loss, x, target, model_out, unreduced_loss = self(x_start, t, cond=cond, ret_pred_x=True)
        loss_100 = unreduced_loss[t<100].mean().detach()
        loss_1000 = unreduced_loss[t>100].mean().detach()

        return loss, loss_100, loss_1000, model_out


    def generate_from_latent(self, latent, batch=5, class_free_weight=0, ddim=False, clip_denoised="static"):
        self.eval()
        latent = latent.squeeze().unsqueeze(0)
        latent = latent.repeat(batch, 1)
        with torch.no_grad():

            sample_fn = self.ddim_sample if ddim else self.sample
            samp,_ = sample_fn(dim=self.model.dim_in_out, batch_size=batch, traj=False, cond=latent, clip_denoised=clip_denoised, class_free_weight=class_free_weight)

        return samp

    def generate_unconditional(self, num_samples):
        self.eval()
        with torch.no_grad():
            # cond_feature = torch.zeros(num_samples, self.model.image_feature_dim).cuda()
            samp,_ = self.sample(dim=self.model.dim_in_out, batch_size=num_samples, traj=False, cond=None)

        return samp