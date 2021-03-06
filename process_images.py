import os
import json
import tensorflow as tf
from redis import Redis
from multiprocessing import set_start_method

import config as cfg

from tfpipe.pipeline.pipeline import Pipeline
from tfpipe.pipeline.image_input import ImageInput
from tfpipe.pipeline.async_predict import AsyncPredict
from tfpipe.pipeline.predict import Predict
from tfpipe.pipeline.annotate_image import AnnotateImage
from tfpipe.pipeline.image_output import ImageOutput

# Redis
from tfpipe.pipeline.redis_capture import RedisCapture
from tfpipe.pipeline.redis_annotate import RedisAnnotate
from tfpipe.pipeline.redis_output import RedisOutput

from time import time

# TODO


def parse_args():
    """ Parses command line arguments. """

    import argparse

    # Parse command line arguments
    ap = argparse.ArgumentParser(
        description="TensorFlow YOLOv4 Image Processing Pipeline")
    ap.add_argument("-i", "--input", default=cfg.MODEL.EVAL.INPUT,
                    help="path to the input image/directory or list of file paths stored in a json file")
    ap.add_argument("-w", "--weights", default=cfg.MODEL.EVAL.WEIGHTS,
                    help="path to weights file")
    ap.add_argument("-s", "--size", type=int, default=cfg.MODEL.EVAL.IMAGE_SIZE,
                    help="the value to which the images will be resized")

    # Model Settings
    ap.add_argument("-f", "--framework", default=cfg.MODEL.EVAL.FRAMEWORK,
                    help="the framework of the model")
    ap.add_argument("--tiny", action="store_true",
                    help="use yolo-tiny instead of yolo")
    ap.add_argument("--iou", default=cfg.MODEL.EVAL.IOU_THRESH,
                    help="iou threshold")
    ap.add_argument("--score", default=cfg.MODEL.EVAL.SCORE_THRESH,
                    help="score threshold")
    ap.add_argument("--classes", default=cfg.MODEL.EVAL.CLASSES,
                    help="file path to classes")

    # Output Settings
    ap.add_argument("-o", "--output", default="output",
                    help="path to the output directory")
    ap.add_argument("--full-output-path", action="store_true",
                    help="saves output to path including its respective input's full basename")
    ap.add_argument("--show", action="store_true",
                    help="display image after prediction")
    ap.add_argument("--meta", action="store_true",
                    help="save prediction metadata")

    # Redis Settings
    ap.add_argument("-r", "--redis", action="store_true",
                    help="signal to use redis capture")
    ap.add_argument("-rh", "--redis-host", default=cfg.REDIS.HOST,
                    help="the host name for redis")
    ap.add_argument("-rp", "--redis-port", default=cfg.REDIS.PORT,
                    help="the port for redis")
    ap.add_argument("-rchi", "--redis-ch-in", default=cfg.REDIS.CH_IN,
                    help="the redis input channel for frames")
    ap.add_argument("-rcho", "--redis-ch-out", default=cfg.REDIS.CH_OUT,
                    help="the redis output channel for predictions")

    # Mutliprocessing Settings
    ap.add_argument("--gpus", default=cfg.GPU.NUM,
                    help="number of GPUs (default: all)")
    ap.add_argument("--vram", type=int, default=cfg.GPU.MEM,
                    help="amount of VRAM per gpu")
    ap.add_argument("--single-process", action="store_true",
                    help="force the pipeline to run in a single process")

    return ap.parse_args()


def main(args):
    """ The main function for image processing. """

    # Create output directory if needed
    os.makedirs(args.output, exist_ok=True)

    # GPU Logging
    tf.debugging.set_log_device_placement(False)

    # tf.config.threading.set_inter_op_parallelism_threads(10)
    # tf.config.threading.set_intra_op_parallelism_threads(10)

    # Image output type
    output_type = "vis_image"

    # Create pipeline tasks
    if not args.single_process:
        set_start_method("spawn", force=True)
        predict = AsyncPredict(args)
    else:
        predict = Predict(args)

    # Wait for models to load before starting input stream
    while not predict.infer_ready():
        pass
    print("Predictors ready! Loading other pipeline tasks...")
    

    if args.redis:
        redis = Redis(host=args.redis_host,
                      port=args.redis_port,
                      db=0,
                      charset='utf-8',
                      decode_responses=True)

        image_input = RedisCapture(
            redis_info=(args.redis_host, args.redis_port, args.redis_ch_in), size=args.size)
        annotate_image = RedisAnnotate(
            output_type, args.iou, args.score, args.classes)
        image_output = RedisOutput(redis, args.redis_ch_out, output_type)
    else:
        image_input = ImageInput(
            path=args.input, size=args.size, meta=args.meta)
        annotate_image = AnnotateImage(
            output_type, args.iou, args.score, args.meta, args.classes)
        image_output = ImageOutput(output_type, args)

    # Create the image processing pipeline
    pipeline = image_input >> predict >> annotate_image >> image_output

    print("All tasks ready! Beginning processing...")

    # Main Loop
    t = time()
    index = 0
    results = list()
    while image_input.is_working() or predict.is_working():
        result = pipeline(None)
        if result != Pipeline.Skip:
            results.append(result)

            # print("Current Index: " + str(index))
            index += 1

    runtime = time() - t
    print(
        f"Images Processed: {index} imgs | Runtime: {runtime} s | Rate: {index / runtime} imgs/s")

    image_input.cleanup()
    predict.cleanup()

    # Metadata
    if args.meta:
        results = [meta for data in results for meta in data["meta"]]
        with open(os.path.join("output", "results.json"), 'w') as f:
            json.dump(results, f)

    # print("Results: " + str(results))


if __name__ == '__main__':
    args = parse_args()
    main(args)
