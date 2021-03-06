import os
import cv2

from tfpipe.pipeline.pipeline import Pipeline

# PTDiag
from ptdiag import PTProcess

class ImageOutput(Pipeline):
    """ Pipeline task that delivers the images to some output. """

    def __init__(self, dst, args, image_ext=".jpg", jpg_quality=None, png_compression=None):
        self.dst = dst
        self.dir = args.output
        self.show_img = args.show
        self.full_base = args.full_output_path
        self.meta = args.meta
        self.image_ext = image_ext

        # 0 - 100 (higher means better). Default is 95.
        self.jpg_quality = jpg_quality

        # 0 - 9 (higher means a smaller size and longer compression time). Default is 3.
        self.png_compression = png_compression

        super().__init__()

        self.ptp = PTProcess("image output")

    def map(self, data):

        # print("im out")
        self.ptp.on()
        if not self.meta:
            self.export_img(data)

        self.ptp.off()
        
        return data

    def export_img(self, data):
        """ Saves image to a file. Also displays the image if self.show is True. """

        image_path = data["image_path"]
        image = data[self.dst]

        # Prepare output for image based on image_path
        dirname, basename = os.path.split(image_path)

        dirname = os.path.join(
            self.dir, dirname) if self.full_base else self.dir
        os.makedirs(dirname, exist_ok=True)

        basename = os.path.splitext(basename)[0] + self.image_ext

        path = os.path.join(dirname, basename)

        # Display
        if self.show_img:
            cv2.imshow(basename, image)
            cv2.waitKey(0)

        if self.image_ext == ".jpg":
            cv2.imwrite(path, image,
                        (cv2.IMWRITE_JPEG_QUALITY, self.jpg_quality) if self.jpg_quality else None)
        elif self.image_ext == ".png":
            cv2.imwrite(path, image,
                        (cv2.IMWRITE_PNG_COMPRESSION, self.png_compression) if self.png_compression else None)
        else:
            raise Exception("Unsupported image format")
