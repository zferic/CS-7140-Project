import gzip
import math
import numpy as np
import os
from PIL import Image
import random
import torch
import torch.utils.data as data

def load_mnist(root):
  # Load MNIST dataset for generating training data.
  path = os.path.join(root, 'train-images-idx3-ubyte.gz')
  with gzip.open(path, 'rb') as f:
    mnist = np.frombuffer(f.read(), np.uint8, offset=16)
    mnist = mnist.reshape(-1, 28, 28)
  return mnist

def load_fixed_set(root, is_train):
  # Load the fixed dataset
  filename = 'mnist_test_seq.npy'
  path = os.path.join(root, filename)
  dataset = np.load(path)
  dataset = dataset[..., np.newaxis]
  return dataset

class MovingMNIST(data.Dataset):
  def __init__(self, root, is_train, n_frames_input, n_frames_output, num_objects,
               transform=None, crop_size=None, occlusion_num=None):
    '''
    param num_objects: a list of number of possible objects.
    '''
    super(MovingMNIST, self).__init__()

    self.dataset = None
    if is_train:
      self.mnist = load_mnist(root)
    else:
      if num_objects[0] != 2:
        self.mnist = load_mnist(root)
      else:
        self.dataset = load_fixed_set(root, False)
    self.length = int(1e4) if self.dataset is None else self.dataset.shape[1]

    self.is_train = is_train
    self.num_objects = num_objects
    self.n_frames_input = n_frames_input
    self.n_frames_output = n_frames_output
    self.n_frames_total = self.n_frames_input + self.n_frames_output
    self.transform = transform
    # For generating data
    self.image_size_ = 100
    self.digit_size_ = 28
    self.step_length_ = 0.2
    self.crop_size = crop_size
    self.occlusion_num = occlusion_num

  def get_random_trajectory(self, seq_length):
    ''' Generate a random sequence of a MNIST digit '''
    canvas_size = self.image_size_ - self.digit_size_
    x = random.random()
    y = random.random()
    theta = random.random() * 2 * np.pi
    v_y = np.sin(theta)
    v_x = np.cos(theta)

    start_y = np.zeros(seq_length)
    start_x = np.zeros(seq_length)
    for i in range(seq_length):
      # Take a step along velocity.
      y += v_y * self.step_length_
      x += v_x * self.step_length_

      # Bounce off edges.
      if x <= 0:
        x = 0
        v_x = -v_x
      if x >= 1.0:
        x = 1.0
        v_x = -v_x
      if y <= 0:
        y = 0
        v_y = -v_y
      if y >= 1.0:
        y = 1.0
        v_y = -v_y
      start_y[i] = y
      start_x[i] = x

    # Scale to the size of the canvas.
    start_y = (canvas_size * start_y).astype(np.int32)
    start_x = (canvas_size * start_x).astype(np.int32)
    return start_y, start_x

  def generate_moving_mnist(self, num_digits=2):
    '''
    Get random trajectories for the digits and generate a video.
    '''
    data = np.zeros((self.n_frames_total, self.image_size_, self.image_size_), dtype=np.float32)
    occ_labels = np.zeros((self.occlusion_num, self.num_objects[0]))
    for n in range(num_digits):
      # Trajectory
      start_y, start_x = self.get_random_trajectory(self.n_frames_total)
      ind = random.randint(0, self.mnist.shape[0] - 1)
      digit_image = self.mnist[ind]
      if self.occlusion_num is not None:
        occ_frame_ids = range(self.n_frames_input - self.occlusion_num + 1)
        occ_id = random.sample(occ_frame_ids, 1)
        occ_ids = range(occ_id[0], occ_id[0] + self.occlusion_num)
      for i in range(self.n_frames_total):
        top    = start_y[i]
        left   = start_x[i]
        bottom = top + self.digit_size_
        right  = left + self.digit_size_
        # Draw digit
        if any(np.equal(i, occ_ids)):
          continue
        else:
          data[i, top:bottom, left:right] = np.maximum(data[i, top:bottom, left:right], digit_image)
      occ_labels[:,n] = occ_ids
    data = data[..., np.newaxis]
    return data, occ_labels

  def __getitem__(self, idx):
    length = self.n_frames_input + self.n_frames_output
    if self.is_train or self.num_objects[0] != 2: #TODO: generate also fro num_obj=2
      # Sample number of objects
      num_digits = random.choice(self.num_objects)
      # Generate data on the fly
      images, occ_labels = self.generate_moving_mnist(num_digits)
    else:
      images = self.dataset[:, idx, ...]
      occ_labels = None #TODO: check test dataset to include MD
    if self.crop_size is not None:
      images = np.stack([self.crop_center(images[i,...,0], self.crop_size[0], self.crop_size[1])
                       for i in range(images.shape[0])])[...,np.newaxis]

    if self.transform is not None:
      images = self.transform(images)
    input = images[:self.n_frames_input]
    if self.n_frames_output > 0:
      output = images[self.n_frames_input:length]
    else:
      output = []

    return input, output

  def __len__(self):
    return self.length

  def crop_center(self, img, cropx, cropy):
    y, x = img.shape
    startx = x // 2 - (cropx // 2)
    starty = y // 2 - (cropy // 2)
    return img[starty:starty + cropy, startx:startx + cropx]