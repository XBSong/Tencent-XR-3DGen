export MODEL_DIR="/data5/sz/model/stable-diffusion-xl-base-1.0"
pretrained_vae_model_name_or_path="/data5/sz/model/sdxl-vae-fp16-fix"
# pretrained_vae_model_name_or_path=""

# controlnet_model_name_or_path="/aigc_cfs/model/controlnet-depth-sdxl-1.0"
controlnet_model_name_or_path=""

train_data_dir="/data5/sz/uv_datasets/human_pos/design_llava"
# train_data_dir="/aigc_cfs_3/layer_tex/uv_datasets/mcwy2_right_pos"
OUTPUT_DIR="/aigc_cfs_3/sz/result/tex_control_2024/xl_human/g4_pos_designonly_llava_5e-5"

max_train_steps=20000
checkpointing_steps=3000
validation_steps=1000
proportion_empty_prompts=0.1
learning_rate=5e-5

current_time=$(date +"%Y-%m-%d_%H-%M")
mkdir -p ${OUTPUT_DIR}
log_txt=${OUTPUT_DIR}/log_${current_time}.txt
exec > >(tee ${log_txt}) 2>&1

accelerate launch --gpu_ids 12,13,14,15 --config_file ./acc4.yaml train_controlnet_sdxl.py \
 --pretrained_model_name_or_path=$MODEL_DIR \
 --output_dir=$OUTPUT_DIR \
 --pretrained_vae_model_name_or_path=${pretrained_vae_model_name_or_path} \
 --controlnet_model_name_or_path=${controlnet_model_name_or_path} \
 --train_data_dir=${train_data_dir} \
 --mixed_precision="fp16" \
 --variant="fp16" \
 --resolution=1024 \
 --learning_rate=${learning_rate} \
 --max_train_steps=${max_train_steps} \
 --checkpointing_steps=${checkpointing_steps} \
 --proportion_empty_prompts=${proportion_empty_prompts} \
 --validation_image "./test_input/pos_top_mcwy2.png" "./test_input/pos_bottom_mcwy2.png" \
 --validation_prompt "red chinese dragon" "firefighter style" \
 --validation_steps=${validation_steps} \
 --train_batch_size=1 \
 --gradient_accumulation_steps=4 \
 --dataloader_num_workers=8 \
 --seed=42

#  --report_to="wandb" \
