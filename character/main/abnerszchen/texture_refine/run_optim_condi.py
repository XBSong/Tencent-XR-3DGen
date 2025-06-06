import os
import argparse
import json

from render.opt_texture import temp_render_opt_obj_texture


def main():
    parser = argparse.ArgumentParser(description='render obj with setting pose')
    parser.add_argument('in_obj', type=str)
    parser.add_argument('in_pose_json', type=str)
    parser.add_argument('cond_img_path', type=str)
    parser.add_argument('out_dir', type=str)
    args = parser.parse_args()

    # Run.
    temp_render_opt_obj_texture(args.in_obj, args.in_pose_json, args.cond_img_path, args.out_dir)

    # Done.
    print("Done.")

#----------------------------------------------------------------------------

if __name__ == "__main__":
    main()
