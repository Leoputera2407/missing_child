from __future__ import print_function
from laedr import modeleag as laedrM
from laedr import network as laedrNetwork
import tensorflow as tf
import numpy as np
import sys

pretrainedLaedrModelPath = './laedr/model/'

class LAEDR_AIM(laedrM.Model):
    def initialize(self):
        self.encoder = laedrNetwork.EncoderNet()
        optim_default = tf.compat.v1.train.AdamOptimizer(0.0001)
        saver = laedrM.Saver(self, optim_default)
        saver.restore(pretrainedLaedrModelPath)



class Missing_Child_Model:
    def __init__(self):
        self.LAEDR_model = LAEDR_AIM()
        self.evaluation_metrics = {}

        self.top_k_cache_id = None
        self.top_k = None
        self.top_k_cache = None


    def forward_pass(self, batch_fathers, batch_mothers, mother_likedness_array):
        # batch_fathers, batch_mothers is N x 128 x 128 x 3 where N is the number of samples.
        # extract Age Invariant Features (AIFs) from both mom and dad
        mother_aif = self.LAEDR_model.encoder(batch_mothers)
        father_aif = self.LAEDR_model.encoder(batch_fathers)
        if os.getenv("ALLOW_GRADIENT_ENCODER") is None:
            # stop gradient so that we don't backpropagate till here.
            mother_aif = tf.stop_gradient(mother_aif)
            father_aif = tf.stop_gradient(father_aif)

        #TODO: implement attention here

        # concatenate both, so we can match input output.
        mf_aif_concatted = tf.concat([mother_aif, father_aif], 1)

        # this is the input-output NN. Matches mom and dad concated
        layer1 = tf.layers.dense(mf_aif_concatted, 90, kernel_regularizer=tf.contrib.layers.l2_regularizer(0.01), activation=tf.nn.tanh, use_bias=True)
        layer2 = tf.layers.dense(layer1, 80, kernel_regularizer=tf.contrib.layers.l2_regularizer(0.01), activation=tf.nn.tanh, use_bias=True)
        layer3 = tf.layers.dense(layer2, 75, kernel_regularizer=tf.contrib.layers.l2_regularizer(0.01), activation=tf.nn.tanh, use_bias=True)
        layer4 = tf.layers.dense(layer3, 60, kernel_regularizer=tf.contrib.layers.l2_regularizer(0.01), activation=tf.nn.tanh, use_bias=True)
        layer5 = tf.layers.dense(layer4, 55, kernel_regularizer=tf.contrib.layers.l2_regularizer(0.01), activation=tf.nn.tanh, use_bias=True)
        model_output = tf.layers.dense(layer5, laedrNetwork.Z_DIM, kernel_regularizer=tf.contrib.layers.l2_regularizer(0.01), activation=tf.nn.tanh, use_bias=True)
        return model_output

    def compute_cxent_loss(self, batch_fathers):
        #TODO? Should we do this at all?
        pass

    def compute_rmse_loss(self, batch_fathers, batch_mothers, mother_likedness_array, batch_children):
        model_output = self.forward_pass(batch_fathers, batch_mothers, mother_likedness_array)
        batch_children_aifs = self.LAEDR_model.encoder(batch_children)
        return tf.sqrt(tf.reduce_mean(tf.square(model_output - batch_children_aifs)))

    def compute_tf_triplet_loss(self, batch_fathers, batch_mothers, mother_likedness_array, batch_child_positives, batch_child_negatives):
        pass



    def compute_triplet_loss(self, batch_fathers, batch_mothers, mother_likedness_array, batch_child_positives, batch_child_negatives):
        positive_child_aifs = tf.math.l2_normalize(self.LAEDR_model.encoder(batch_child_positives), axis=1)
        negative_child_aifs = tf.math.l2_normalize(self.LAEDR_model.encoder(batch_child_negatives), axis=1)
        model_output = tf.math.l2_normalize(self.forward_pass(batch_fathers, batch_mothers, mother_likedness_array), axis=1)
        # triplet loss on the AIFs 
        # triplet loss as introduced by VGGFACE : Maximising vector distance for unrelated pairs, and minimising otherwise.

        d_pos = tf.reduce_sum(tf.square(model_output - positive_child_aifs), 1)
        d_neg = tf.reduce_sum(tf.square(model_output - negative_child_aifs), 1)

        triplet_loss_margin = tf.constant(0.70, name="triplet_loss_margin")

        triplet_loss = tf.maximum(0., triplet_loss_margin + d_pos - d_neg)
        triplet_loss = tf.reduce_mean(triplet_loss)

        return triplet_loss

    # train one batch. Returns the batch loss.
    def train_one_step(self, optimizer, batch_fathers, batch_mothers, mother_likedness_array, batch_child_positives, batch_child_negatives):
        gradients, variables = zip(*optimizer.compute_gradients(lambda: self.compute_triplet_loss(batch_fathers, batch_mothers, mother_likedness_array, batch_child_positives, batch_child_negatives)))
        gradients, _ = tf.clip_by_global_norm(gradients, 5.0)
        optimizer.apply_gradients(zip(gradients, variables))
        batch_loss = self.compute_triplet_loss(batch_fathers, batch_mothers, mother_likedness_array, batch_child_positives, batch_child_negatives)

        return batch_loss 




    # evaluate the top k accuracy of our model. If the child is in the top k most similar results, then we got it right.
    # this implements caching, so we can just compute the bulk of the operations once to measure the top 10, top 5 , top 2 etc. of a specific batch. The cache is invalidated by cache_id, or if the top_k is higher than what was cached.
    def evaluate_accuracy(self, batch_size, batch_fathers, batch_mothers, mother_likedness_array, batch_children, top_n = 1, cache_id=None):
        if cache_id is None \
        or cache_id != self.top_k_cache_id \
        or self.top_k < top_n \
        or cache_id != self.top_k_cache_id:
            # recompute the diff array ( N x N array of 0 (child not found) and 1s (child found)
            self.top_k = top_n
            self.top_k_cache_id = cache_id

            child_aif = self.LAEDR_model.encoder(batch_children)
            child_aif = tf.math.l2_normalize(child_aif, axis=1)
            #tf.stop_gradient(child_aif)
            # child_aif is N x D, model_output is N x D as well. 
            # Need N by N matrix. Every model output needs a distance with a real child. Then compute top n.

            model_output = self.forward_pass(batch_fathers, batch_mothers, mother_likedness_array)
            model_output = tf.math.l2_normalize(model_output, axis=1)

            model_output_squared_norms = tf.reduce_sum(tf.math.square(model_output), 1)
            child_aif_squared_norms = tf.reduce_sum(tf.math.square(child_aif), 1)
            squared_norms = model_output_squared_norms + child_aif_squared_norms

            squared_distance_matrix = squared_norms- 2 * tf.matmul(model_output, child_aif,  transpose_a=False, transpose_b=True)
            distance_matrix = tf.sqrt(squared_distance_matrix)
            _, candidates = tf.nn.top_k(tf.negative(distance_matrix), k=top_n, sorted=True)
            indices = tf.constant([i for i in range(batch_size)], dtype=np.int32, shape= [batch_size])
            indices = tf.reshape(indices, [batch_size, 1])
            # i am paranoid so I put the below. You don't need it because broadcasting i
            # is implicit.
            indices = tf.broadcast_to(indices, tf.shape(candidates))
            diff = candidates - indices

            diff = tf.equal(diff, 0) # if any element is 0, that means the child is found.
            self.top_k_cache = diff
        else:
            # use cache.
            diff = self.top_k_cache
            if top_n < self.top_k:
                diff = diff[: , :top_n]

        child_found_vec =tf.reduce_any(diff, 1) # see if any child is found.
        child_found_vec = tf.cast(child_found_vec, np.float32)
        acc_score = tf.reduce_mean(child_found_vec)

        return acc_score

        

    





        
