#!/usr/bin/env python
import tensorflow as tf
import os
import numpy as np
from tensorflow.python.keras.backend import set_session
from laedr.modeleag import Saver
from model_v3 import create_model_v3
import data_loader as data

config = tf.compat.v1.ConfigProto()
config.gpu_options.allow_growth=True
tf.compat.v1.enable_eager_execution(config=config)
set_session(tf.get_default_session())

EPOCHS = 1200
BATCHES_PER_EPOCH = 20
BATCH_SIZE = 50  # this is the amount of samples for each M, F, CP, CN to be considered at each step. Note that because each MF pair has a positive and negative child, the training set batch size is actually 2 * BATCH_SIZE.

TF_DEVICE=os.getenv("TF_DEVICE") if os.getenv("TF_DEVICE") is not None else "GPU:0"

learning_rate = float(os.getenv("LEARNING_RATE")) if os.getenv("LEARNING_RATE") is not None else 0.0001

CKPT_FOLDER = "./model_checkpoints_v3"
CKPT_EXTENSION = "hdf5"
CKPT_PREFIX = "v3_weights"
#NOTE: do not change the format below:
WEIGHTS_CKPT_FORMAT = CKPT_PREFIX + ".{epoch:02d}-{val_loss:.2f}." + CKPT_EXTENSION

class ModelCheckpointer(tf.keras.callbacks.Callback):
    def __init__(self, model_saver, save_freq=1):
        super(ModelCheckpointer,self).__init__()
        self.model_saver = model_saver
        self.save_freq = save_freq
        self.epochs_elapsed = 0

    def on_epoch_end(self, epoch, logs={}):
        self.epochs_elapsed += 1
        if self.epochs_elapsed % self.save_freq == 0:
            print("saving model", logs)
            print("val loss: ", logs["val_loss"])
            self.model_saver.save(os.path.join(CKPT_FOLDER, WEIGHTS_CKPT_FORMAT.format(epoch=epoch, val_loss=logs["val_loss"])))



print("using tf device {}, learning rate {}".format(TF_DEVICE, learning_rate))

tboard_logdir="./tboard_logs"

if __name__=='__main__':
    mcm_model = create_model_v3() 

    optimizer = tf.compat.v1.train.AdamOptimizer(learning_rate=learning_rate)
    initial_epoch = 0 
    model_saver = Saver(mcm_model, optimizer)
    if os.path.isdir(CKPT_FOLDER):
        print("restoring from {}".format(CKPT_FOLDER))
        ckpt_path = model_saver.restore(CKPT_FOLDER)
        if ckpt_path is not None:
            initial_epoch = int(ckpt_path.split(CKPT_PREFIX+".")[1].split("-")[0])

    mcm_model.compile(optimizer=optimizer, loss='binary_crossentropy', metrics=['accuracy'])
    print("model instantiated")

    data_loader = data.Data_reader()
    data_loader.set_traintest_split(0.75)


    tensorboard_callback = tf.keras.callbacks.TensorBoard(log_dir=tboard_logdir)
    model_checkpoint_callback = ModelCheckpointer(model_saver, save_freq=5)

    with tf.device(TF_DEVICE):
        mcm_model.fit_generator(
            data.train_generator(data_loader, BATCH_SIZE), 
            validation_data=data.test_generator(data_loader, BATCH_SIZE),
            validation_steps=10, 
            validation_freq=5,# how many training epochs before we validate.
            epochs=EPOCHS, 
            steps_per_epoch=BATCHES_PER_EPOCH,
            callbacks=[tensorboard_callback, model_checkpoint_callback],
            initial_epoch=initial_epoch
        )

        mcm_model.evaluate_generator(
            data.test_generator(data_loader, BATCH_SIZE)
        )

