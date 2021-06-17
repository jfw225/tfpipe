import cv2
import tensorflow as tf
import numpy as np
from multiprocessing import Process, Queue, Value

from core.config import cfg
from pipeline.pipeline import Pipeline

from time import time


class AsyncPredictor(Process):
    """ The asynchronous predictor. """

    def __init__(self, args, device, task_queue, result_queue):
        self.size = args.size
        self.weights = args.weights
        self.framework = args.framework
        self.device = device
        self.task_queue = task_queue
        self.result_queue = result_queue

        self.ready = Value('i', 0)

        super().__init__(daemon=True)

    def run(self):
        """ The main prediction loop. """

        with tf.device(self.device):

            # Create the model and prediction function
            print("Building Model for Device: " + self.device)
            if self.framework == 'tflite':
                pass  # come back if we need tflite
            else:
                model = tf.keras.models.load_model(self.weights)
                predict = model.predict

            print("Inferencing Test Image: " + self.device)
            image = cv2.cvtColor(cv2.imread(cfg.INIT_IMG), cv2.COLOR_BGR2RGB)
            image = [cv2.resize(image, (self.size, self.size)) / 255.0]
            image = np.asanyarray(image).astype(np.float32)
            predict(tf.constant(image))

            # Set ready flag
            self.ready.value = 1
            print("Ready: " + self.device)
            # counter = 0
            while True:
                # print(self.device)
                data = self.task_queue.get()
                if data == Pipeline.Exit:
                    break

                t = time()
                predictions = predict(data["predictions"])
                print(f"Device: {self.device} | Time: {time() - t} s")
                conf = predictions[:, :, 4:]

                data["predictions"] = (tf.reshape(predictions[:, :, 0:4], (1, -1, 1, 4)),
                                       tf.reshape(conf, (1, -1, tf.shape(conf)[-1])))

                self.result_queue.put(data)

                # counter += 1
                # print(self.device, "done")


class AsyncPredict(Pipeline):
    """ The pipeline task for multi-process predicting. """

    def __init__(self, args):
        num_gpus = min(len(tf.config.list_physical_devices('GPU')), args.gpus)
        num_cpus = min(len(tf.config.list_physical_devices('CPU')), args.cpus)
        assert num_gpus > 0 or num_cpus > 0, "Must specify number of gpus or cpus"

        # Number of inputs and outputs
        self.inx = self.outx = 0

        self.task_queue = Queue()
        self.result_queue = Queue()
        self.workers = list()

        # Create GPU Predictors
        for gpu_id in range(num_gpus):
            worker = AsyncPredictor(
                args, f"GPU:{gpu_id}", self.task_queue, self.result_queue)
            self.workers.append(worker)

        # Create CPU Predictors
        for cpu_id in range(num_cpus):
            worker = AsyncPredictor(
                args, f"CPU:{cpu_id}", self.task_queue, self.result_queue)
            self.workers.append(worker)

        # Start the Jobs
        for w in self.workers:
            w.start()

        super().__init__()

    def map(self, data):
        if data != Pipeline.Empty:
            self.put(data)

        return self.get() if self.output_ready() else Pipeline.Skip

    def put(self, data):
        """ Puts data in the task queue. """

        self.inx += 1
        self.task_queue.put(data)

    def get(self):
        """ Returns first element in the output queue. """

        self.outx += 1
        return self.result_queue.get()

    def output_ready(self):
        """ Returns True if there is element in the output queue. """

        return not self.result_queue.empty()

    def infer_ready(self):
        """ Returns True when each of the predictors are ready for inference. """

        return all([worker.ready.value for worker in self.workers])

    def is_working(self):
        """ Working while num inputs != num outputs and while queues are not empty. """

        return self.inx != self.outx or not self.task_queue.empty() or not self.result_queue.empty()

    def cleanup(self):
        """ Kills all predictors. """

        for _ in self.workers:
            self.task_queue.put(Pipeline.Exit)
