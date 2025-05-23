import os

os.environ['http_proxy'] = ''
os.environ['https_proxy'] = ''
os.environ['no_proxy'] = 'localhost, 127.0.0.1, ::1'

import sys
sys.path.append(os.path.abspath(os.getcwd()))
import argparse
import gradio as gr
from ipdb import set_trace as st
import shutil
import subprocess
import numpy as np
from os import listdir
from omegaconf import OmegaConf
import glob
from easydict import EasyDict as edict
import torch
import uuid
import shutil

from overall_pipeline_v2 import overall_pipeline


from mediapipe import solutions
from mediapipe.framework.formats import landmark_pb2
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

from segment_anything import sam_model_registry, SamPredictor

from diffusers import AutoPipelineForInpainting
from diffusers.utils import load_image, make_image_grid

from gradio_client import Client, handle_file


CURRENT_PATH = os.getcwd()
OUT_DIR = f'{CURRENT_PATH}/output/web/'


base_options = python.BaseOptions(model_asset_path='./face_landmarker_v2_with_blendshapes.task')
options = vision.FaceLandmarkerOptions(base_options=base_options,output_face_blendshapes=True,
                                        output_facial_transformation_matrixes=True,num_faces=1)
face_detector = vision.FaceLandmarker.create_from_options(options)

sam_checkpoint = "/aigc_cfs_2/weimao/pretrained_model_cache/sam_vit_h_4b8939.pth"
model_type = "vit_h"
device = "cuda"
sam = sam_model_registry[model_type](checkpoint=sam_checkpoint)
sam.to(device=device)
sam_predictor = SamPredictor(sam)

inpainting_pipeline = AutoPipelineForInpainting.from_pretrained(
    "/aigc_cfs_2/weimao/pretrained_model_cache/stable-diffusion-xl-1.0-inpainting-0.1", torch_dtype=torch.float16, variant="fp16"
    )
inpainting_pipeline.enable_model_cpu_offload()

# overall_pipeline(args.file_path, face_detector, sam_predictor, inpainting_pipeline)

# initialise the cuteyou 2d pipeline
# cute_you2d_pipeline = Client('http://cute_you2d_pipeline/')
cute_you2d_pipeline = Client('http://cute_you2d_pipeline/')

def generate(face_img, cartoon_img):
    
    print(f'>>> receive job {face_img}')
    # random_uid = uuid.uuid4()
    try:
        cute_you2d_pipeline.predict(input_text="a cartoon character, with less highlights and more face details", 
                                                input_image=handle_file(face_img))
        cartoon_img = '/aigc_cfs_2/jiayuuyang/cuteyou.png'
        print('>>> Cuteyou2D succeeded')
    except Exception as e:
        print(">>> Cuteyou2D error:", e)
    
    img_name = os.path.basename(face_img).split('.')[0]
    os.makedirs(OUT_DIR + '/' + img_name, exist_ok=True)
    shutil.copyfile(face_img, OUT_DIR + '/' + img_name + '/' + os.path.basename(face_img))
    _, mesh_zip = overall_pipeline(cartoon_img, face_detector, sam_predictor, inpainting_pipeline, out_dir=OUT_DIR + '/' + img_name)
    return mesh_zip

def launch(
    port,
    listen=False,
):
    lock_path = 'runing'

    global listen_port
    listen_port = port

    css = """
    #config-accordion, #logs-accordion {color: black !important;}
    .dark #config-accordion, .dark #logs-accordion {color: white !important;}
    .stop {background: darkred !important;}
    """
    
    with gr.Blocks(
        title="Cuteyou3D",
        css=css,
    ) as demo:
        with gr.Row(equal_height=True):
            header = """
            Cuteyou3D: Given a front image of a person, Cuteyou3D generates a 3D cartoon character. It takes around 100 seconds to generate
            """
            gr.Markdown(header)
            
        with gr.Row(equal_height=False):
            with gr.Column(scale=1):
                with gr.Row():
                    face_img = gr.Image(
                        value=None,
                        label="Input face image",
                        interactive=True,
                        type="filepath"
                        )
                with gr.Row():
                    cartoon_img = gr.Image(
                        value=None,
                        label="Cuteyou face image",
                        interactive=True,
                        type="filepath",
                        visible=False
                        )
                with gr.Row():
                    generate_btn = gr.Button(value="Generate", variant="primary")
            with gr.Column(scale=1):
                with gr.Row():
                    # head_mesh = gr.Model3D(value=None, label="Mesh", interactive=False)
                    head_mesh = gr.File(value=None, label="Mesh ZIP", interactive=False)
                # with gr.Row():
                #     download = gr.Button(value="Download", variant="primary")
        

        generate_btn.click(
            fn=generate,
            inputs=[
                face_img,
                cartoon_img,
            ],
            outputs=[
                head_mesh
            ],
            concurrency_limit=1
        )


    launch_args = {"server_port": port}
    if listen:
        launch_args["server_name"] = "0.0.0.0"
    demo.queue().launch(**launch_args)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--listen", action="store_true")
    parser.add_argument("--port", type=int, default=80)
    args = parser.parse_args()

    launch(
        args.port,
        listen=args.listen
    )