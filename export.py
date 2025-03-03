# Copyright (c) 2021 - present / Neuralmagic, Inc. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Helper script to export ViT models to ONNX
##########
Command help:
usage: export.py [-h] --checkpoint CHECKPOINT [--config CONFIG] \
    [--recipe RECIPE] [--no-qat-conv] [--batch-size BATCH_SIZE] \
    [--image-shape IMAGE_SHAPE [IMAGE_SHAPE ...]] \
    [--save-dir SAVE_DIR] [--filename FILENAME]
Export ViT models to ONNX
optional arguments:
  -h, --help            show this help message and exit
  --checkpoint CHECKPOINT
                        The ViT pytorch checkpoint to export
  --config CONFIG, -c CONFIG
                        The config used to train the ViT model,
                        for ex: Defaults to look for args.yaml in 
                        checkpoint directory.
  --recipe RECIPE, -r RECIPE
                        Path or SparseZoo stub to the recipe used for training,
                        omit if no recipe used.
  --no-qat-conv, -N     Flag to prevent conversion of a QAT(Quantization Aware
                        Training) Graph to a Quantized Graph
  --batch-size BATCH_SIZE, -b BATCH_SIZE
                        The batch size to use while exporting the Model graph to
                        ONNX;Defaults to 1
  --image-shape IMAGE_SHAPE [IMAGE_SHAPE ...], -S IMAGE_SHAPE [IMAGE_SHAPE ...]
                        The image shape in (C, S, S) format to use for exporting
                        the Model graph to ONNX; Defaults to (3, 550, 550)
  --save-dir SAVE_DIR, -s SAVE_DIR
                        The directory to save exported models to; Defaults to
                        "./exported_models"
  --filename FILENAME, -n FILENAME  The name to use for saving the exported ONNX model
##########
Example usage:
python export.py --checkpoint ./checkpoints/vit_base_patch32_224-224_pruned.pth.tar \
    --recipe ./recipes/vit_base.85.recal.config.yaml 
##########
Example Two:
python export.py --checkpoint ./quantized-checkpoint/vit_base_patch32_224-224_pruned.pth.tar \
    --recipe ./recipes/vit_base.85.quant.config.yaml \
    --save-dir ./exported-models \
    --filename vit_base_patch32_224-224 \
    --batch-size 1 \
    --image-shape 3 550 550 \
    --config ./quantized-checkpoint/args.yaml
"""

import os
import yaml
import argparse
from argparse import Namespace
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
import torch
from timm.models import create_model
from timm.optim import create_optimizer_v2, optimizer_kwargs
from sparseml.pytorch.optim import ScheduledModifierManager
from sparseml.pytorch.utils import export_onnx

logging.basicConfig(level=logging.INFO)


@dataclass
class ExportArgs:
    """
    Typed arguments for exporting a ViT model to ONNX
    """

    checkpoint: Path
    config: str
    recipe: str
    no_qat_conv: bool
    batch_size: int
    image_shape: Iterable
    save_dir: str
    filename: str

    def __post_init__(self):
        """
        post-initialization processing and validation
        """
        self.checkpoint = Path(self.checkpoint)

        if not self.checkpoint.exists():
            raise FileNotFoundError(
                f"The checkpoint {self.checkpoint} does " f"not exist."
            )

        self.config = Path(self.config or os.path.dirname(self.checkpoint) + "/args.yaml")
        
        if not self.config.exists():
            raise FileNotFoundError(
                f"The config file {self.config} does " f"not exist."
            )
        
        self.image_shape = tuple(self.image_shape)

        if not self.save_dir:
            self.save_dir = 'onnx'
        if self.filename:
            head, extension = os.path.splitext(self.filename)
            if not extension:
                self.filename += '.onnx'
        else:
            self.filename = str(self.checkpoint.with_suffix(".onnx").name)



def parse_args() -> ExportArgs:
    """
    Add and parse arguments for exporting a ViT model to ONNX
    
    :return: A ExportArgs Object with typed arguments
    """
    parser = argparse.ArgumentParser(description="Export ViT models to ONNX")

    parser.add_argument(
        "--checkpoint",
        type=str,
        required=True,
        help="The ViT pytorch checkpoint to export",
    )

    parser.add_argument(
        "--config",
        "-c",
        type=str,
        help="The config used to train the ViT model. By default "
        "the parser will attempt to open args.yaml in the same "
        "directory as the checkpoint",
    )

    parser.add_argument(
        "--recipe",
        "-r",
        type=str,
        default=None,
        help="Path or SparseZoo stub to the recipe used for training, "
        "omit if no recipe used. If no recipe given, "
        "the checkpoint recipe will be applied if present.",
    )

    parser.add_argument(
        "--no-qat-conv",
        "-N",
        action="store_true",
        help="Flag to prevent conversion of a QAT(Quantization Aware Training) "
             "Graph to a Quantized Graph",
    )

    parser.add_argument(
        "--batch-size",
        "-b",
        type=int,
        default=1,
        help="The batch size to use while exporting the Model graph to ONNX;"
        "Defaults to 1",
    )

    parser.add_argument(
        "--image-shape",
        "-S",
        type=int,
        nargs="+",
        default=(3, 550, 550),
        help="The image shape in (C, S, S) format to use for exporting the "
        "Model graph to ONNX; Defaults to (3, 550, 550)",
    )

    parser.add_argument(
        "--save-dir",
        type=str,
        default=None,
        help="The directory for saving the exported ONNX model."
             "If none, defaults to onnx/",
    )

    parser.add_argument(
        "--filename",
        type=str,
        default=None,
        help="The name of the exported ONNX model."
             "If none, defaults to checkpoint-name.onnx",
    )

    args = parser.parse_args()
    return ExportArgs(**vars(args))


def export(args: ExportArgs):

    # Load model-specific configs
    with open(args.config, 'r') as f:
            cfg = yaml.safe_load(f)
            cfg = Namespace(**cfg)
                
    model = create_model(
            cfg.model,
            pretrained=cfg.pretrained,
            num_classes=cfg.num_classes,
            drop_rate=cfg.drop,
            drop_connect_rate=cfg.drop_connect, 
            drop_path_rate=cfg.drop_path,
            drop_block_rate=cfg.drop_block,
            global_pool=cfg.gp,
            bn_tf=cfg.bn_tf,
            bn_momentum=cfg.bn_momentum,
            bn_eps=cfg.bn_eps,
            scriptable=cfg.torchscript,
            checkpoint_path=None,
            )

    # Apply recipe to model and then load in saved weights
    manager = ScheduledModifierManager.from_yaml(args.recipe)
    manager.apply(model)
    batch_shape = (args.batch_size, *args.image_shape)
    state_dict = torch.load(args.checkpoint)
    model.load_state_dict(state_dict['state_dict'])

    # export to onnx graph   
    export_onnx(
        module=model,
        sample_batch=torch.randn(*batch_shape),
        file_path=os.path.join(args.save_dir, args.filename),
        convert_qat= not args.no_qat_conv,
    )


if __name__ == "__main__":
    export_args = parse_args()
    export(export_args)
