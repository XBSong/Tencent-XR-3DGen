from typing import Any, Dict, Optional
from diffusers.models import AutoencoderKL, UNet2DConditionModel
from diffusers.schedulers import KarrasDiffusionSchedulers

from model.zero123plus_unet import UNet2DConditionModelRamping

import numpy
import torch
import torch.nn as nn
import torch.utils.checkpoint
import torch.distributed
import transformers
from collections import OrderedDict
from PIL import Image
from torchvision import transforms
from transformers import CLIPImageProcessor, CLIPTextModel, CLIPTokenizer

import diffusers
from diffusers import (
    AutoencoderKL,
    DDPMScheduler,
    DiffusionPipeline,
    EulerAncestralDiscreteScheduler,
    UNet2DConditionModel,
    ImagePipelineOutput
)
from diffusers.image_processor import VaeImageProcessor
from diffusers.models.attention_processor import Attention, AttnProcessor, XFormersAttnProcessor, AttnProcessor2_0
from diffusers.utils.import_utils import is_xformers_available


def to_rgb_image(maybe_rgba: Image.Image):
    if maybe_rgba.mode == 'RGB':
        return maybe_rgba
    elif maybe_rgba.mode == 'RGBA':
        rgba = maybe_rgba
        img = numpy.random.randint(127, 128, size=[rgba.size[1], rgba.size[0], 3], dtype=numpy.uint8)
        img = Image.fromarray(img, 'RGB')
        img.paste(rgba, mask=rgba.getchannel('A'))
        return img
    else:
        raise ValueError("Unsupported image type.", maybe_rgba.mode)

class ReferenceOnlyAttnProc(torch.nn.Module):
    def __init__(
        self,
        chained_proc,
        enabled=False,
        name=None
    ) -> None:
        super().__init__()
        self.enabled = enabled
        self.chained_proc = chained_proc
        self.name = name

    def __call__(
        self, attn: Attention, hidden_states, encoder_hidden_states=None, attention_mask=None,
        mode="w", ref_dict: dict = None, is_cfg_guidance = False
    ) -> Any:
        if encoder_hidden_states is None:
            encoder_hidden_states = hidden_states
        if self.enabled and is_cfg_guidance:
            res0 = self.chained_proc(attn, hidden_states[:1], encoder_hidden_states[:1], attention_mask)
            hidden_states = hidden_states[1:]
            encoder_hidden_states = encoder_hidden_states[1:]
        if self.enabled:
            if mode == 'w':
                ref_dict[self.name] = encoder_hidden_states
            elif mode == 'r':
                encoder_hidden_states = torch.cat([encoder_hidden_states, ref_dict.pop(self.name)], dim=1)
            elif mode == 'm':
                encoder_hidden_states = torch.cat([encoder_hidden_states, ref_dict[self.name]], dim=1)
            else:
                assert False, mode
        res = self.chained_proc(attn, hidden_states, encoder_hidden_states, attention_mask)
        if self.enabled and is_cfg_guidance:
            res = torch.cat([res0, res])
        return res


class RefOnlyNoisedUNet(torch.nn.Module):
    # def __init__(self, unet: UNet2DConditionModel, train_sched: DDPMScheduler, val_sched: EulerAncestralDiscreteScheduler) -> None:
    def __init__(self, unet:UNet2DConditionModelRamping, train_sched: DDPMScheduler, val_sched: EulerAncestralDiscreteScheduler) -> None:
        super().__init__()
        self.unet = unet
        self.train_sched = train_sched
        self.val_sched = val_sched

        unet_lora_attn_procs = dict()
        for name, _ in unet.attn_processors.items():
            if torch.__version__ >= '2.0':
                default_attn_proc = AttnProcessor2_0()
            elif is_xformers_available():
                default_attn_proc = XFormersAttnProcessor()
            else:
                default_attn_proc = AttnProcessor()
            unet_lora_attn_procs[name] = ReferenceOnlyAttnProc(
                default_attn_proc, enabled=name.endswith("attn1.processor"), name=name
            )
        unet.set_attn_processor(unet_lora_attn_procs)

    def __getattr__(self, name: str):
        try:
            return super().__getattr__(name)
        except AttributeError:
            return getattr(self.unet, name)

    def forward_cond(self, noisy_cond_lat, timestep, encoder_hidden_states, class_labels, ref_dict, is_cfg_guidance, **kwargs):
        if is_cfg_guidance:
            encoder_hidden_states = encoder_hidden_states[1:]
            class_labels = class_labels[1:]

        self.unet.set_is_controlnet(is_controlnet=False)

        self.unet(
            noisy_cond_lat, timestep,
            encoder_hidden_states=encoder_hidden_states,
            class_labels=class_labels,
            cross_attention_kwargs=dict(mode="w", ref_dict=ref_dict),
            **kwargs
        )
    
    def ramping_add(self, encoder_hidden_states_prompt, cond_encoded_clip):
        return self.unet.ramping_add(encoder_hidden_states_prompt, cond_encoded_clip)

    # def forward(
    #     self, sample, timestep, encoder_hidden_states, class_labels=None,
    #     *args, cross_attention_kwargs,
    #     down_block_res_samples=None, mid_block_res_sample=None,
    #     **kwargs
    # ):
    def forward(
        self, 
        sample, 
        timestep, 
        encoder_hidden_states_prompt=None,
        cond_encoded_clip=None,
        drop_idx=None,
        encoder_hidden_states=None, 
        class_labels=None,
        *args, 
        cross_attention_kwargs,
        down_block_res_samples=None, 
        mid_block_res_sample=None,
        **kwargs
    ):
        # print("ref running !!!")
        # breakpoint()
        if encoder_hidden_states_prompt is not None and encoder_hidden_states is None:
            encoder_hidden_states = self.ramping_add(encoder_hidden_states_prompt, cond_encoded_clip)
            # encoder_hidden_states = encoder_hidden_states.to(encoder_hidden_states_prompt.dtype)
        if drop_idx is not None:
            encoder_hidden_states[drop_idx] = encoder_hidden_states_prompt[drop_idx]

        cond_lat = cross_attention_kwargs['cond_lat']
        is_cfg_guidance = cross_attention_kwargs.get('is_cfg_guidance', False)
        noise = torch.randn_like(cond_lat, memory_format=torch.contiguous_format)

        if self.training:
            # print("training !!!!")
            noisy_cond_lat = self.train_sched.add_noise(cond_lat, noise, timestep)
            noisy_cond_lat = self.train_sched.scale_model_input(noisy_cond_lat, timestep)
        else:
            # print("test !!!!")
            noisy_cond_lat = self.val_sched.add_noise(cond_lat, noise, timestep.reshape(-1))
            noisy_cond_lat = self.val_sched.scale_model_input(noisy_cond_lat, timestep.reshape(-1))

        assert(cond_lat.shape[0] == 2), "batch size must be 2 include negative condition,"\
            "because different sample have different k, v length, when have different num of condition views"
        
        bs, vn, c, h, w = noisy_cond_lat.shape
        noisy_cond_lat = noisy_cond_lat.view(bs*vn, c, h, w)

        # print("timestep: ", timestep.shape)
        # print("encoder_hidden_states: ", encoder_hidden_states.shape)
        # breakpoint()

        # timestep_v = [torch.cat([step.view((1,))] * vn) for step in timestep]
        encoder_hidden_states_v = [torch.stack([hs] * vn) for hs in encoder_hidden_states]
        # timestep_v = torch.cat(timestep_v, dim=0)
        encoder_hidden_states_v = torch.cat(encoder_hidden_states_v, dim=0)

        # print("timestep_v: ", timestep_v.shape)
        # print("encoder_hidden_states_v: ", encoder_hidden_states_v.shape)
        # breakpoint()

        ref_dict = {}

        # breakpoint()

        # print("noisy_cond_lat: ", noisy_cond_lat.shape)
        # print("encoder_hidden_states: ", encoder_hidden_states.shape)
        # print("timestep: ", timestep.shape)
        # breakpoint()

        self.forward_cond(
            noisy_cond_lat, 
            timestep,
            encoder_hidden_states_v, 
            class_labels,
            ref_dict, 
            is_cfg_guidance, 
            **kwargs
        )

        for key, value in ref_dict.items():
            _, _, dim = value.shape
            ref_dict[key] = value.view(bs, -1, dim)

        weight_dtype = self.unet.dtype
        
        # print("after forward cond running !!!")
        # breakpoint()

        self.unet.set_is_controlnet(is_controlnet=True)
        
        return self.unet(
            sample, timestep,
            encoder_hidden_states, *args,
            class_labels=class_labels,
            cross_attention_kwargs=dict(mode="r", ref_dict=ref_dict, is_cfg_guidance=is_cfg_guidance),
            down_block_additional_residuals=[
                sample.to(dtype=weight_dtype) for sample in down_block_res_samples
            ] if down_block_res_samples is not None else None,
            mid_block_additional_residual=(
                mid_block_res_sample.to(dtype=weight_dtype)
                if mid_block_res_sample is not None else None
            ),
            **kwargs
        )


def scale_latents(latents):
    latents = (latents - 0.22) * 0.75
    return latents


def unscale_latents(latents):
    latents = latents / 0.75 + 0.22
    return latents


def scale_image(image):
    image = image * 0.5 / 0.8
    return image


def unscale_image(image):
    image = image / 0.5 * 0.8
    return image


class DepthControlUNet(torch.nn.Module):
    def __init__(self, unet: RefOnlyNoisedUNet, controlnet: Optional[diffusers.ControlNetModel] = None, conditioning_scale=1.0) -> None:
        super().__init__()
        self.unet = unet
        if controlnet is None:
            self.controlnet = diffusers.ControlNetModel.from_unet(unet.unet)
        else:
            self.controlnet = controlnet
        DefaultAttnProc = AttnProcessor2_0
        if is_xformers_available():
            DefaultAttnProc = XFormersAttnProcessor
        self.controlnet.set_attn_processor(DefaultAttnProc())
        self.conditioning_scale = conditioning_scale

    def __getattr__(self, name: str):
        try:
            return super().__getattr__(name)
        except AttributeError:
            return getattr(self.unet, name)

    def forward(self, sample, timestep, encoder_hidden_states, class_labels=None, *args, cross_attention_kwargs: dict, **kwargs):
        # print("running controlnet !!!")
        # print("scale: ", self.conditioning_scale)
        # breakpoint()
        cross_attention_kwargs = dict(cross_attention_kwargs)
        # print("keys:", cross_attention_kwargs.keys())
        # breakpoint()
        control_depth = cross_attention_kwargs.pop('control_depth')
        down_block_res_samples, mid_block_res_sample = self.controlnet(
            sample,
            timestep,
            encoder_hidden_states=encoder_hidden_states,
            controlnet_cond=control_depth,
            conditioning_scale=self.conditioning_scale,
            return_dict=False,
        )
        # print(mid_block_res_sample.shape)
        # breakpoint()
        # self.unet.set_is_controlnet(is_controlnet=True)

        return self.unet(
            sample,
            timestep,
            encoder_hidden_states=encoder_hidden_states,
            down_block_res_samples=down_block_res_samples,
            mid_block_res_sample=mid_block_res_sample,
            cross_attention_kwargs=cross_attention_kwargs
        )


class ModuleListDict(torch.nn.Module):
    def __init__(self, procs: dict) -> None:
        super().__init__()
        self.keys = sorted(procs.keys())
        self.values = torch.nn.ModuleList(procs[k] for k in self.keys)

    def __getitem__(self, key):
        return self.values[self.keys.index(key)]


class SuperNet(torch.nn.Module):
    def __init__(self, state_dict: Dict[str, torch.Tensor]):
        super().__init__()
        state_dict = OrderedDict((k, state_dict[k]) for k in sorted(state_dict.keys()))
        self.layers = torch.nn.ModuleList(state_dict.values())
        self.mapping = dict(enumerate(state_dict.keys()))
        self.rev_mapping = {v: k for k, v in enumerate(state_dict.keys())}

        # .processor for unet, .self_attn for text encoder
        self.split_keys = [".processor", ".self_attn"]

        # we add a hook to state_dict() and load_state_dict() so that the
        # naming fits with `unet.attn_processors`
        def map_to(module, state_dict, *args, **kwargs):
            new_state_dict = {}
            for key, value in state_dict.items():
                num = int(key.split(".")[1])  # 0 is always "layers"
                new_key = key.replace(f"layers.{num}", module.mapping[num])
                new_state_dict[new_key] = value

            return new_state_dict

        def remap_key(key, state_dict):
            for k in self.split_keys:
                if k in key:
                    return key.split(k)[0] + k
            return key.split('.')[0]

        def map_from(module, state_dict, *args, **kwargs):
            all_keys = list(state_dict.keys())
            for key in all_keys:
                replace_key = remap_key(key, state_dict)
                new_key = key.replace(replace_key, f"layers.{module.rev_mapping[replace_key]}")
                state_dict[new_key] = state_dict[key]
                del state_dict[key]

        self._register_state_dict_hook(map_to)
        self._register_load_state_dict_pre_hook(map_from, with_module=True)


class Zero123PlusPipeline(diffusers.StableDiffusionPipeline):
    tokenizer: transformers.CLIPTokenizer
    text_encoder: transformers.CLIPTextModel
    vision_encoder: transformers.CLIPVisionModelWithProjection

    feature_extractor_clip: transformers.CLIPImageProcessor
    # unet: UNet2DConditionModel
    unet: UNet2DConditionModelRamping
    scheduler: diffusers.schedulers.KarrasDiffusionSchedulers

    vae: AutoencoderKL
    ramping: nn.Linear

    feature_extractor_vae: transformers.CLIPImageProcessor

    depth_transforms_multi = transforms.Compose([
        transforms.ToTensor(),
        # transforms.Normalize([0.5], [0.5])
    ])

    def __init__(
        self,
        vae: AutoencoderKL,
        text_encoder: CLIPTextModel,
        tokenizer: CLIPTokenizer,
        # unet: UNet2DConditionModel,
        unet:UNet2DConditionModelRamping,
        scheduler: KarrasDiffusionSchedulers,
        vision_encoder: transformers.CLIPVisionModelWithProjection,
        feature_extractor_clip: CLIPImageProcessor, 
        feature_extractor_vae: CLIPImageProcessor,
        ramping_coefficients: Optional[list] = None,
        safety_checker=None,
    ):
        DiffusionPipeline.__init__(self)

        self.register_modules(
            vae=vae, 
            text_encoder=text_encoder, 
            tokenizer=tokenizer,
            unet=unet, 
            scheduler=scheduler, 
            safety_checker=None,
            vision_encoder=vision_encoder,
            feature_extractor_clip=feature_extractor_clip,
            feature_extractor_vae=feature_extractor_vae
        )
        self.register_to_config(ramping_coefficients=ramping_coefficients)
        self.vae_scale_factor = 2 ** (len(self.vae.config.block_out_channels) - 1)
        self.image_processor = VaeImageProcessor(vae_scale_factor=self.vae_scale_factor)

    def prepare(self):
        ddpm_config = {}
        for key, value in self.scheduler.config.items():
            if key in ["set_alpha_to_one", "skip_prk_steps"]:
                continue
            ddpm_config[key] = value

        # train_sched = DDPMScheduler.from_config(self.scheduler.config)
        train_sched = DDPMScheduler.from_config(ddpm_config)
        # if isinstance(self.unet, UNet2DConditionModel):
        # if isinstance(self.unet, UNet2DConditionModelRamping):
        if not isinstance(self.unet, RefOnlyNoisedUNet):
            self.unet = RefOnlyNoisedUNet(self.unet, train_sched, self.scheduler).eval()

    def add_controlnet(self, controlnet: Optional[diffusers.ControlNetModel] = None, conditioning_scale=1.0):
        # print("control 11111")
        self.prepare()
        # print("control 22222222")
        self.unet = DepthControlUNet(self.unet, controlnet, conditioning_scale)
        return SuperNet(OrderedDict([('controlnet', self.unet.controlnet)]))

    def encode_condition_image(self, image: torch.Tensor):
        image = self.vae.encode(image).latent_dist.sample()
        return image
    
    def vae_decode(self, latents_grid, hnum=4, wnum=2, imgsize=256):  # [b, 4, 32*4, 32*2]
        latent_size = imgsize // 8
        assert list(latents_grid.shape) == [
            1,
            4,
            latent_size * hnum,
            latent_size * wnum,
        ], f"latents shape should be [1, 4, {latent_size*hnum}, {latent_size*wnum}]"
        image_grid = torch.zeros([1, 3, imgsize * hnum, imgsize * wnum]).to(dtype=latents_grid.dtype)
        for hi in range(hnum):
            for wi in range(wnum):
                image_grid[
                    :, :, imgsize * hi : imgsize * (hi + 1), imgsize * wi : imgsize * (wi + 1)
                ] = self.vae.decode(
                    latents_grid[
                        :, :, latent_size * hi : latent_size * (hi + 1), latent_size * wi : latent_size * (wi + 1)
                    ]
                    / self.vae.config.scaling_factor,
                    return_dict=False,
                )[0]
        return image_grid

    @torch.no_grad()
    def __call__(
        self,
        # image: Image.Image = None,
        images_list = [],
        prompt = "",
        *args,
        num_images_per_prompt: Optional[int] = 1,
        guidance_scale=4.0,
        conditioning_scale=1.5,
        depth_image: Image.Image = None,
        controlnet = None,
        output_type: Optional[str] = "pil",
        # infer_times = 0,
        width=1024,
        height=1024,
        num_inference_steps=28,
        return_dict=True,
        **kwargs
    ):
        image_size = int(width // 2)
        hnum = int(height // image_size)
        wnum = int(width // image_size)
        self.prepare()
        if images_list[0] is None:
            raise ValueError("Inputting embeddings not supported for this pipeline. Please pass an image.")
        assert not isinstance(images_list[0], torch.Tensor)

        image_vae_list = []
        for image in images_list:
            image = to_rgb_image(image)
            if image is None:
                return None
            image_1 = self.feature_extractor_vae(images=image, return_tensors="pt").pixel_values
            image = image_1.to(device=self.vae.device, dtype=self.vae.dtype)
            image_vae_list.append(image)
        image_vae = torch.cat(image_vae_list, dim=0)

        # print("image_vae: ", image_vae.shape)
        # breakpoint()

        cond_lat = self.encode_condition_image(image_vae) ### vae encode
        cond_lat = cond_lat[None]

        # print("cond_lat: ", cond_lat.shape)
        # breakpoint()

        # conditioning_scale = 1.5
        # if infer_times == 0:
        self.unet = DepthControlUNet(self.unet, controlnet, conditioning_scale)
        # breakpoint()
        self.unet = self.unet.to(self.vae.device, dtype=self.vae.dtype)
        if image is None:
            raise ValueError("Inputting embeddings not supported for this pipeline. Please pass an image.")
        assert not isinstance(images_list[0], torch.Tensor)
        # print("111111")
        # image = to_rgb_image(image)
        # image_1 = self.feature_extractor_vae(images=image, return_tensors="pt").pixel_values
        image_2 = self.feature_extractor_clip(images=images_list[0], return_tensors="pt").pixel_values
        # print("222222")
        # if depth_image is not None and hasattr(self.unet, "controlnet"):
        #     # print("depth 1111")
        #     depth_image = to_rgb_image(depth_image)
        #     depth_image = self.depth_transforms_multi(depth_image).to(
        #         device=self.unet.controlnet.device, dtype=self.unet.controlnet.dtype
        #     )

        # print("depth 1111")
        depth_image = to_rgb_image(depth_image)
        depth_image = self.depth_transforms_multi(depth_image).to(
            device=self.unet.controlnet.device, dtype=self.unet.controlnet.dtype
        )

        # print("33333")
        # image = image_1.to(device=self.vae.device, dtype=self.vae.dtype)
        image_2 = image_2.to(device=self.vae.device, dtype=self.vae.dtype)
        # cond_lat = self.encode_condition_image(image)
        # print("44444")
        if guidance_scale > 1:
            # print("55555")
            negative_lat = self.encode_condition_image(torch.zeros_like(image_vae))[None]
            cond_lat = torch.cat([negative_lat, cond_lat])
        # print("66666")
        encoded = self.vision_encoder(image_2, output_hidden_states=False)
        global_embeds = encoded.image_embeds
        global_embeds = global_embeds.unsqueeze(-2)

        # print("777777")
        
        if hasattr(self, "encode_prompt"):
            encoder_hidden_states = self.encode_prompt(
                prompt,
                self.device,
                num_images_per_prompt,
                False
            )[0]
        else:
            encoder_hidden_states = self._encode_prompt(
                prompt,
                self.device,
                num_images_per_prompt,
                False
            )

        # if "ramping_coefficients" in self.unet.config:
        #     # print("888888")
        #     encoder_hidden_states = self.unet.ramping_add(encoder_hidden_states, global_embeds)
        # else:
        #     ramp = global_embeds.new_tensor(self.config.ramping_coefficients).unsqueeze(-1)
        #     encoder_hidden_states = encoder_hidden_states + global_embeds * ramp

        encoder_hidden_states = self.unet.ramping_add(encoder_hidden_states, global_embeds)

        # ramp = global_embeds.new_tensor(self.config.ramping_coefficients).unsqueeze(-1)
        # encoder_hidden_states = encoder_hidden_states + global_embeds * ramp

        if num_images_per_prompt > 1:
            bs_embed, *lat_shape = cond_lat.shape
            assert len(lat_shape) == 3
            cond_lat = cond_lat.repeat(1, num_images_per_prompt, 1, 1)
            cond_lat = cond_lat.view(bs_embed * num_images_per_prompt, *lat_shape)

        cak = dict(cond_lat=cond_lat)
        # if hasattr(self.unet, "controlnet"):
            # cak['control_depth'] = depth_image
        cak['control_depth'] = depth_image
        # print("here 1111 !!!")
        # breakpoint()
        latents: torch.Tensor = super().__call__(
            None,
            *args,
            cross_attention_kwargs=cak,
            guidance_scale=guidance_scale,
            num_images_per_prompt=num_images_per_prompt,
            prompt_embeds=encoder_hidden_states,
            num_inference_steps=num_inference_steps,
            output_type='latent',
            width=width,
            height=height,
            **kwargs
        ).images
        latents = unscale_latents(latents)
        if not output_type == "latent":
            # image = unscale_image(self.vae.decode(latents / self.vae.config.scaling_factor, return_dict=False)[0])
            image = unscale_image(self.vae_decode(latents, hnum=2, wnum=2, imgsize=int(width//2)))
        else:
            image = latents

        image = self.image_processor.postprocess(image, output_type=output_type)
        if not return_dict:
            return (image,)

        return ImagePipelineOutput(images=image)